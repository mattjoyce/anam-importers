#!/usr/bin/env python3
"""anam_agentmail fetch (anam card 242): copies the attachments of the messages in an
AgentMail inbox into a spool folder, byte-exact, with a manifest.csv saying what came and
what failed. It reads the inbox and writes only under the spool folder. It holds no Anam
token and sends nothing to Anam: shaping the spool into records is a later step.

Layout: <spool>/<stem>/<attachment filename>, where <stem> is the first 16 hex digits of
the SHA-256 of the message id, so a name never carries a character a path cannot. A file
already spooled with the size the inbox reports is kept, so a re-run is a no-op.

    AGENTMAIL_API_KEY=... python3 agentmail/fetch.py --inbox me@agentmail.to --spool ./spool

Exit status: 0 when every attachment is ok, 1 when any failed, 2 on a bad call.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

# DEFAULT_* are choices someone could make differently (anam card 151): each is a flag.
DEFAULT_BASE_URL = "https://api.agentmail.to"
# Every call fails fast rather than hanging; 30 s outlasts a slow PDF over a slow link.
DEFAULT_TIMEOUT = 30.0
# 50 is the most a page returns, so the fewest round trips.
DEFAULT_PAGE_SIZE = 50
MANIFEST = "manifest.csv"
# Not configurable: the manifest's columns are what a reader of the spool relies on.
COLUMNS = ["message_id", "timestamp", "from", "subject", "attachment_id", "filename",
           "saved_path", "bytes", "sha256", "status", "detail"]


class Inbox:
    """The few AgentMail calls the fetch needs, with a deadline on each."""

    def __init__(self, base_url: str, inbox: str, key: str, timeout: float):
        self.base = base_url.rstrip("/")
        self.inbox = urllib.parse.quote(inbox, safe="@")
        self.key = key
        self.timeout = timeout

    def _get(self, url: str, auth: bool = True) -> bytes:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.key}"} if auth else {})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (https base from a flag)
            return resp.read()

    def messages(self, page_size: int) -> Iterator[Dict[str, Any]]:
        token: Optional[str] = None
        while True:
            q = {"limit": page_size}
            if token:
                q["page_token"] = token
            page = json.loads(self._get(f"{self.base}/v0/inboxes/{self.inbox}/messages?{urllib.parse.urlencode(q)}"))
            yield from page.get("messages") or []
            token = page.get("next_page_token")
            if not token:
                return

    def attachment(self, message_id: str, attachment_id: str) -> bytes:
        mid = urllib.parse.quote(message_id, safe="")
        meta = json.loads(self._get(f"{self.base}/v0/inboxes/{self.inbox}/messages/{mid}/attachments/{attachment_id}"))
        # The download link is signed and carries its own authority: no bearer token goes to it.
        return self._get(meta["download_url"], auth=False)


def stem(message_id: str) -> str:
    return hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:16]


# Not configurable: a filesystem's name limit is 255 bytes, and a name this long keeps room for ".part".
MAX_NAME_BYTES = 200


def safe_name(name: str) -> str:
    """A filename with no directory, control character or excess length in it, so a message
    cannot write outside its folder or make a write fail. A long name keeps its extension and
    gains a hash of the whole name, so two long names stay two files."""
    base = Path(name.replace("\\", "/")).name
    base = "".join(c for c in base if c.isprintable()).strip().lstrip(".")
    if len(base.encode("utf-8")) > MAX_NAME_BYTES:
        ext = Path(base).suffix[:16]
        digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]
        head = base[: -len(ext)] if ext else base
        head = head.encode("utf-8")[: MAX_NAME_BYTES - len(ext) - 13].decode("utf-8", "ignore")
        base = f"{head}-{digest}{ext}"
    return base or "attachment"


def cell(value: Any) -> Any:
    """A manifest cell a spreadsheet will not run as a formula: sender and subject are the
    mail's, not ours, so a leading = + - @ tab or CR gets a quote in front."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def check(body: bytes, expected: Optional[int], content_type: str, filename: str) -> Optional[str]:
    """Why these bytes are not the attachment, or None when they are."""
    if expected is not None and len(body) != expected:
        return f"{len(body)} bytes, the inbox says {expected}"
    if (content_type == "application/pdf" or filename.lower().endswith(".pdf")) and not body.startswith(b"%PDF"):
        return "not a PDF: no %PDF header"
    return None


def fetch_one(inbox: Inbox, spool: Path, msg: Dict[str, Any], att: Dict[str, Any]) -> Dict[str, Any]:
    name = safe_name(att.get("filename") or "attachment")
    path = spool / stem(msg["message_id"]) / name
    row = {"message_id": msg["message_id"], "timestamp": msg.get("timestamp", ""), "from": msg.get("from", ""),
           "subject": msg.get("subject", ""), "attachment_id": att["attachment_id"], "filename": name,
           "saved_path": str(path.relative_to(spool)), "bytes": "", "sha256": "", "status": "ok", "detail": ""}
    expected = att.get("size")
    if path.is_file() and (expected is None or path.stat().st_size == expected):
        body = path.read_bytes()
        row["detail"] = "kept"
    else:
        try:
            body = inbox.attachment(msg["message_id"], att["attachment_id"])
        except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
            row.update(status="failed", detail=f"download: {exc}")
            return row
        why = check(body, expected, att.get("content_type", ""), name)
        if why:
            row.update(status="failed", detail=why)
            return row
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_name(path.name + ".part")
            tmp.write_bytes(body)
            tmp.replace(path)
        except (OSError, ValueError) as exc:
            row.update(status="failed", detail=f"write: {exc}")
            return row
    row.update(bytes=str(len(body)), sha256=hashlib.sha256(body).hexdigest())
    return row


def run(inbox: Inbox, spool: Path, page_size: int) -> List[Dict[str, Any]]:
    spool.mkdir(parents=True, exist_ok=True)
    rows = [fetch_one(inbox, spool, m, a) for m in inbox.messages(page_size) for a in m.get("attachments") or []]
    with (spool / MANIFEST).open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows({k: cell(v) for k, v in r.items()} for r in rows)
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--inbox", required=True, help="the inbox address")
    ap.add_argument("--spool", required=True, type=Path, help="folder the attachments are written under")
    ap.add_argument("--base-url", default=DEFAULT_BASE_URL)
    ap.add_argument("--key-env", default="AGENTMAIL_API_KEY", help="name of the variable holding the API key")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="seconds each call may take")
    ap.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    args = ap.parse_args(argv)
    key = os.environ.get(args.key_env, "")
    if not key:
        print(f"{args.key_env} is not set", file=sys.stderr)
        return 2
    if args.timeout <= 0 or not 1 <= args.page_size <= 100:
        print("--timeout must be above 0 and --page-size within 1..100", file=sys.stderr)
        return 2
    rows = run(Inbox(args.base_url, args.inbox, key, args.timeout), args.spool, args.page_size)
    failed = [r for r in rows if r["status"] != "ok"]
    print(f"{len(rows) - len(failed)} ok, {len(failed)} failed, manifest {args.spool / MANIFEST}")
    for r in failed:
        print(f"  failed {r['filename']} ({r['message_id']}): {r['detail']}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
