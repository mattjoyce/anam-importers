#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""anam_documents: shapes a folder of documents into record.document envelopes for Anam,
one batch event at a time (anam card 103). It is Anam's built-in documents worker
(internal/capture/documents), moved, so the same file from either path is the same
facet with the same payload.

Each regular file is one document. Its fact-time is not in its bytes: a sidecar
`<file>.meta.yaml` beside it says `date: YYYY-MM-DD` and anything else worth saying
(title, note). A file without one refuses the run, naming the sidecar to write.
Dot-files and dot-directories are skipped; sidecars are read, never sent.

Identity is the folder-relative path, and the payload carries the file's sha256, its
size and its media type, measured here; the sidecar may not declare them. The bytes
go to Anam's library through anam_submit, which posts each file named in a batch's
`documents` before its envelopes (POST /v1/documents), so only Anam writes the
library and no bytes ride in an event.

Commands:
- poll   : every document under documents_dir, in batches, as one snapshot
- handle : on a folder_watch event, the same as poll
- health : documents_dir is readable and every document in it has a usable sidecar
"""

from __future__ import annotations

import hashlib
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import batches, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402


def _records() -> Any:
    """records/run.py, loaded under its own name: its YAML reader resolves scalars as
    Go's yaml.v3 did for the worker, and both importers must agree on a sidecar."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("anam_records_run", HERE.parent / "records" / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


records = _records()

BATCH_EVENT = "anam_documents.batch"
TYPE = "record.document"
# SIDECAR and MEASURED are not configurable: the sidecar's name is the worker's, which
# every sidecar already written follows, and MEASURED is what the Definition says the
# file, not the sidecar, decides.
SIDECAR = ".meta.yaml"
MEASURED = ("path", "sha256", "bytes", "media_type")

# ZONE is where record.document's Definition reads a sidecar's date, a day with no
# zone. Nothing else says where the day was, so each document's source_time says the
# zone is an assumption (anam card 198). Not configurable: the Definition, which this
# importer does not carry, places the day, and another zone here would make
# source_time say an instant fact_time denies.
ZONE = "Australia/Sydney"


class BadDocuments(ductile.Failure):
    """A document that cannot be described. Retrying will not help."""

    def __init__(self, message: str):
        super().__init__(message, retry=False)


def _plain(node: Any, where: str) -> Any:
    """A composed YAML node as plain values, scalars resolved as Go's yaml.v3 resolved
    them for the worker: the records importer's reader, shared so both agree."""
    try:
        return records.plain(node, where)
    except records.BadRecords as exc:
        raise BadDocuments(str(exc)) from exc


def sidecar(path: Path) -> Dict[str, Any]:
    """The payload's starting fields from `<file>.meta.yaml`."""
    import yaml

    side = Path(str(path) + SIDECAR)
    try:
        text = side.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise BadDocuments(f"{path.name}: write {side} with `date: YYYY-MM-DD` "
                           "(the document's own date, not today's)") from exc
    except OSError as exc:
        raise ductile.Failure(f"sidecar {side}: {exc}", retry=True) from exc
    try:
        root = yaml.compose(text, Loader=records._loader())
    except yaml.YAMLError as exc:
        raise BadDocuments(f"{side}: {exc}") from exc
    fields = _plain(root, str(side)) if root is not None else None
    if not isinstance(fields, dict):
        raise BadDocuments(f"{side}: not a mapping")
    date = fields.get("date")
    if not isinstance(date, str) or not date:
        raise BadDocuments(f"{side}: `date: YYYY-MM-DD` is required")
    for k in MEASURED:
        if k in fields:
            raise BadDocuments(f"{side}: {k} is measured from the file, not declared")
    if "source_time" in fields:
        raise BadDocuments(f"{side}: source_time is the importer's, saying how date was read; not declared")
    return fields


def media_type(path: Path) -> str:
    """By extension, the way a browser or a share names it: a label on the pointer,
    not a verdict on the bytes. The same table Anam's worker reads, for the common
    kinds; anything else is application/octet-stream."""
    # The kinds the live library holds, spelled as Anam's container named them, so a
    # cut-over resends every reference as a no-op (2026-10-14). Not configurable:
    # another spelling supersedes every reference that carries it.
    known = {".pdf": "application/pdf", ".md": "text/markdown", ".txt": "text/plain",
             ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp", ".svg": "image/svg+xml", ".html": "text/html", ".htm": "text/html",
             ".json": "application/json", ".csv": "text/csv", ".xml": "text/xml", ".zip": "application/zip",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ext = path.suffix.lower()
    if ext in known:
        return known[ext]
    guessed, _ = mimetypes.guess_type(path.name, strict=True)
    return guessed or "application/octet-stream"


def documents(root: Path) -> List[Path]:
    """Every regular file under root, by path: dot-directories, dot-files and sidecars
    skipped, as the worker walked."""
    out: List[Path] = []
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in names:
            p = Path(here) / name
            if name.startswith(".") or name.endswith(SIDECAR) or not p.is_file() or p.is_symlink():
                continue
            out.append(p)
    return sorted(out, key=lambda p: str(p))


def describe(root: Path, path: Path, person: str) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """One document as its envelope and the file anam_submit hands Anam."""
    rel = path.relative_to(root).as_posix()
    payload = sidecar(path)
    h = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                size += len(chunk)
    except OSError as exc:
        raise ductile.Failure(f"document {path}: {exc}", retry=True) from exc
    payload.update({"path": rel, "sha256": h.hexdigest(), "bytes": size, "media_type": media_type(path),
                    "source_time": {"value": payload["date"], "zone": ZONE, "basis": "assumption"}})
    env: Dict[str, Any] = {"type": TYPE, "payload": payload}
    if person:
        env["asserted_person"] = person
    return env, {"path": rel, "file": str(path)}


def scan(config: Dict[str, Any], person: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, str]]]:
    root = Path(str(config.get("documents_dir", ""))).expanduser()
    if not root.is_dir():
        raise ductile.Failure(f"no documents_dir at {root}", retry=False)
    envs, files = [], []
    for p in documents(root):
        env, doc = describe(root, p, person)
        envs.append(env)
        files.append(doc)
    return envs, files


def assumed(envs: List[Dict[str, Any]]) -> List[str]:
    """The log line that says each sidecar's date was read in an assumed zone."""
    if not envs:
        return []
    return [f"{len(envs)} document date(s) read as {ZONE} days (basis assumption): a sidecar's date names no zone"]


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    envs, files = scan(config, str(config["person_id"]))
    by_path = {f["path"]: f for f in files}
    groups = list(batches(envs))
    events = [ductile.event(BATCH_EVENT, {
        "envelopes": g, "definitions": [], "current_versions": True,
        "documents": [by_path[e["payload"]["path"]] for e in g],
        "batch": f"documents {i + 1}/{len(groups)}",
    }) for i, g in enumerate(groups)]
    # Every document in the folder is everything held, so the run is a snapshot.
    if events:
        for ev, part in zip(events, snapshot_parts(len(events), [TYPE])):
            ev["payload"]["snapshot"] = part
    return ductile.ok(f"{len(envs)} document(s) in {len(events)} batch(es)", events=events, logs=assumed(envs))


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    return poll(request)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    envs, _ = scan(config, "health-check")
    return ductile.ok(f"{len(envs)} document(s), each with a usable sidecar", logs=assumed(envs))


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
