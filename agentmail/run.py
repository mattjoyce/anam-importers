#!/usr/bin/env python3
"""agentmail: spools the mail in an AgentMail inbox for the invoice chain (anam card 242).

One folder per message under mail_spool, named by the first 16 hex digits of the SHA-256 of
the message id:

    <mail_spool>/<key>/message.json
    <mail_spool>/<key>/attachments/<n>-<safe name>          byte-exact
    <mail_spool>/<key>/attachments/<n>-<safe name>.txt      pdftotext -layout of each PDF

A folder is built under a temporary name beside the others and renamed into place, so a
reader never sees half of one, and it is never edited after. A message with an attachment
that fails fetch.py's checks (the size the inbox reports, %PDF on a PDF) or whose text
cannot be extracted is not spooled at all: it is named in the logs and tried again next
poll. A folder already there is skipped, so a second poll writes nothing.

The plugin reads the inbox and writes under mail_spool. It sends nothing back, reads no
instruction text in a mail, holds no Anam token, and logs ids, counts and file names only,
never the API key (the gateway hands it over as the vault secret key_secret names, agentmail_api_key unless set).

Commands:
- poll   : spool the messages not yet spooled; one agentmail.pdf event per new PDF
- health : the key reads the inbox, mail_spool is writable, pdftotext is present
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from agentmail import fetch  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

PDF_EVENT = "agentmail.pdf"
# The vault secret holding the key, unless key_secret names another. Ductile's vault
# names are lowercase and global, so an instance names its own, as anam_submit's
# token_secret does.
DEFAULT_KEY_SECRET = "agentmail_api_key"

# DEFAULT_* are choices someone could make differently (anam card 151): each is a key.
DEFAULT_BASE_URL = fetch.DEFAULT_BASE_URL
DEFAULT_TIMEOUT = fetch.DEFAULT_TIMEOUT
DEFAULT_PAGE_SIZE = fetch.DEFAULT_PAGE_SIZE
# Not configurable: a bound on pdftotext, so one malformed PDF cannot hold the poll; a PDF
# that needs longer is a failed attachment, which the next poll retries.
PDFTOTEXT_TIMEOUT = 60
# Not configurable: the layout of a payload folder is the contract with the purchase gate.
TMP_PREFIX = ".tmp-"


class Settings(NamedTuple):
    """This run's config, read and checked once, at the start of a command."""

    inbox: str
    spool: Path
    base_url: str
    timeout: float
    page_size: int


def settings(config: Dict[str, Any]) -> Settings:
    return Settings(
        inbox=cfg.text(config, "agentmail_inbox", ""),
        spool=Path(cfg.text(config, "mail_spool", "")),
        base_url=cfg.url(config, "base_url", DEFAULT_BASE_URL),
        timeout=cfg.number(config, "timeout", DEFAULT_TIMEOUT, 0, 600, low_open=True),
        page_size=cfg.integer(config, "page_size", DEFAULT_PAGE_SIZE, 1, 100),
    )


def inbox_of(request: Dict[str, Any], s: Settings) -> fetch.Inbox:
    name = str((request.get("config") or {}).get("key_secret") or DEFAULT_KEY_SECRET)
    key = (request.get("secrets") or {}).get(name, "")
    if not key:
        raise ductile.Failure(f"no {name} secret granted to this instance", retry=False)
    return fetch.Inbox(s.base_url, s.inbox, key, s.timeout)


def is_pdf(att: Dict[str, Any], name: str) -> bool:
    return att.get("content_type") == "application/pdf" or name.lower().endswith(".pdf")


def pdf_text(pdf: Path, out: Path) -> Optional[str]:
    """Write pdftotext -layout of pdf to out; the reason it could not, or None."""
    try:
        done = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), str(out)],
                              capture_output=True, timeout=PDFTOTEXT_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"pdftotext: {type(exc).__name__}"
    if done.returncode != 0:
        return f"pdftotext exited {done.returncode}"
    return None


class Spooled(NamedTuple):
    """A folder written: its path and the PDFs in it, as (pdf, text) paths."""

    folder: Path
    pdfs: List[tuple]


def spool_message(inbox: fetch.Inbox, spool: Path, msg: Dict[str, Any], inbox_name: str) -> Spooled:
    """Build the message's folder under a temporary name and rename it into place. Raises
    ValueError naming the attachment and why when any attachment fails, leaving nothing
    behind."""
    key = fetch.stem(msg["message_id"])
    final = spool / key
    tmp = Path(tempfile.mkdtemp(prefix=f"{TMP_PREFIX}{key}-", dir=spool))
    try:
        attdir = tmp / "attachments"
        attdir.mkdir()
        entries: List[Dict[str, Any]] = []
        pdfs: List[tuple] = []
        for n, att in enumerate(msg.get("attachments") or [], start=1):
            name = fetch.safe_name(att.get("filename") or "attachment")
            saved = f"{n}-{name}"
            label = f"attachment {n} ({name})"
            try:
                body = inbox.attachment(msg["message_id"], att["attachment_id"])
            except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
                raise ValueError(f"{label}: download: {type(exc).__name__}") from exc
            why = fetch.check(body, att.get("size"), att.get("content_type", ""), name)
            if why:
                raise ValueError(f"{label}: {why}")
            (attdir / saved).write_bytes(body)
            text = None
            if is_pdf(att, name):
                text = saved + ".txt"
                why = pdf_text(attdir / saved, attdir / text)
                if why:
                    raise ValueError(f"{label}: {why}")
                pdfs.append((final / "attachments" / saved, final / "attachments" / text))
            entries.append({"n": n, "attachment_id": att.get("attachment_id"), "filename": att.get("filename"),
                            "saved_as": saved, "content_type": att.get("content_type"), "size": len(body),
                            "sha256": hashlib.sha256(body).hexdigest(), "text": text})
        # AgentMail's own verdicts, as given (SPF, DKIM, DMARC and the domains each was
        # judged on); null when the message carries none. Nothing here is our judgment.
        record = {"message_id": msg["message_id"], "inbox": inbox_name, "from": msg.get("from"),
                  "to": msg.get("to"), "subject": msg.get("subject"), "received_at": msg.get("timestamp"),
                  "auth": msg.get("authentication_results"), "attachments": entries}
        (tmp / "message.json").write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            os.rename(tmp, final)
        except OSError as exc:
            raise ValueError(f"rename: {type(exc).__name__}") from exc
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return Spooled(final, pdfs)


def clear_stale(spool: Path) -> None:
    """A temporary folder left by a poll that died; nothing reads one, so it goes."""
    for p in spool.glob(TMP_PREFIX + "*"):
        shutil.rmtree(p, ignore_errors=True)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    s = settings(request.get("config") or {})
    inbox = inbox_of(request, s)
    try:
        s.spool.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ductile.Failure(f"mail_spool: {exc.strerror or type(exc).__name__}", retry=False) from exc
    spool = s.spool.resolve()
    clear_stale(spool)
    events: List[Dict[str, Any]] = []
    logs: List[str] = []
    seen = new = skipped = failed = 0
    try:
        for msg in inbox.messages(s.page_size):
            seen += 1
            key = fetch.stem(msg["message_id"])
            if (spool / key).exists():
                skipped += 1
                continue
            try:
                done = spool_message(inbox, spool, msg, s.inbox)
            except (ValueError, OSError) as exc:
                failed += 1
                logs.append(f"failed {key}: {exc}")
                continue
            new += 1
            for i, (pdf, text) in enumerate(done.pdfs):
                events.append(ductile.event(PDF_EVENT, {"payload_dir": str(done.folder), "pdf": str(pdf),
                                                        "input_file": str(text)}, dedupe_key=f"{key}-{i}"))
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        # URLError and HTTPError name the status and host, never a header.
        raise ductile.Failure(f"inbox: {type(exc).__name__}: {exc}", retry=True) from exc
    logs.insert(0, f"{seen} messages, {new} spooled, {skipped} already there, {failed} failed, {len(events)} PDFs")
    return ductile.ok(f"{new} spooled, {failed} failed", events, logs)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    s = settings(request.get("config") or {})
    inbox = inbox_of(request, s)
    problems: List[str] = []
    try:
        next(iter(inbox.messages(1)), None)
    except (urllib.error.URLError, OSError, ValueError, KeyError) as exc:
        problems.append(f"the key does not read the inbox: {type(exc).__name__}: {exc}")
    try:
        s.spool.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=s.spool):
            pass
    except OSError as exc:
        problems.append(f"mail_spool is not writable: {exc.strerror or type(exc).__name__}")
    if shutil.which("pdftotext") is None:
        problems.append("pdftotext is not on the path")
    if problems:
        raise ductile.Failure("; ".join(problems), retry=False)
    return ductile.ok("the key reads the inbox, mail_spool is writable, pdftotext is present")


if __name__ == "__main__":
    ductile.run({"poll": poll, "health": health})
