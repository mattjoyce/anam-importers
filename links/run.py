#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18", "pyyaml>=6"]
# ///
"""anam_links: shapes a folder of files into record.link envelopes for Anam, one
batch event at a time (anam card 165). A record.link is a file Anam remembers but
does not hold: its name, hash, size, media type and date, never its bytes. Nothing
is posted to Anam's library, and nothing is served from the folder.

One instance declares one folder (links_dir, named root_name in every fact) under one
identity mode, because one folder's files share a nature:

- path    : a file that stays put and changes in place; new bytes supersede, a move is
            a new facet. id is path:<root_name>/<relative path>.
- content : a photo or screenshot, never edited but moved and renamed; a move
            supersedes, new bytes are a new facet. id is content:<sha256>.
- id      : a note with a declared id in its frontmatter; a move and an edit both
            supersede. id is id:<frontmatter id>; a file without one is skipped.

Fact-time is the first that answers: a Markdown file's frontmatter date, EXIF
DateTimeOriginal, a YYYY-MM-DD prefix on the file name, then mtime; date_from says
which. A date with no zone is read in the instance's zone. mtime is weak (an edit
moves it) and is refused for Markdown.

A file the importer cannot read or date is skipped and reported, never the run: the
premise of the type is that files drift. A file known from an earlier run and not
seen for unseen_after complete runs is superseded with unseen: true; one that comes
back is superseded back. The importer keeps that count, and the payload it last sent
for each file, in state_file, outside links_dir: the only state it keeps, and none of
Anam's. An unreachable links_dir is no run, not a miss for every file under it. A
run in which a file could not be read is not labelled a snapshot, so Anam never calls
a facet absent for a file the importer did not get to read.

Commands:
- poll   : every file under links_dir, in batches, as one snapshot; counts as a run
- handle : on a folder_watch event, the same as poll
- health : links_dir and state_file are readable and every file conforms; writes nothing
"""

from __future__ import annotations

import hashlib
import json
import mimetypes
import os
import re
import struct
import sys
import zoneinfo
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import clock as clk  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

TYPE = "record.link"
BATCH_EVENT = "anam_links.batch"

# Not configurable: the Definition's vocabulary. MODES are the identity modes and the
# prefixes /id carries; SOURCES are date_from's values, in the order they are tried.
MODES = ("path", "content", "id")
SOURCES = ("frontmatter", "exif", "filename", "mtime")

# DEFAULT_UNSEEN_AFTER is how many complete runs a known file may be missing before
# the importer says so with an unseen version, unless config's unseen_after says
# otherwise: three, so a file moved and moved back, or a folder mid-sync, is not
# declared unseen for one run's absence. A person's tolerance for drift is theirs.
DEFAULT_UNSEEN_AFTER = 3

# Not configurable: what the importer reads of a file. MARKDOWN names the files whose
# frontmatter is read and whose mtime is refused; EXIF_KINDS the files whose EXIF is
# read (JPEG and TIFF only: the reader below is a page, and HEIC, PNG and WebP would
# each be another); FRONT_READ bounds the frontmatter read; EXIF_READ bounds a TIFF's.
MARKDOWN = (".md", ".markdown")
EXIF_KINDS = (".jpg", ".jpeg", ".tif", ".tiff")
FRONT_READ = 64 * 1024
EXIF_READ = 1 << 20
FILENAME_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?![0-9])")
STATE_VERSION = 1


class Skipped(Exception):
    """A file the run leaves out, with why. The run goes on. unread says the file
    could not be read at all, as against read and excluded by this instance's rules
    (no declared id, no date for a Markdown file, a second file with the same id):
    a run that left a file unread is not labelled a snapshot."""

    def __init__(self, reason: str, unread: bool = False):
        super().__init__(reason)
        self.unread = unread


@dataclass(frozen=True)
class Settings:
    """An instance's config, read and checked once at the start of a command."""

    links_dir: Path
    root_name: str
    person: str
    identity: str
    zone: zoneinfo.ZoneInfo
    unseen_after: int
    state_file: Path


def settings(config: Dict[str, Any]) -> Settings:
    links_dir = Path(cfg.text(config, "links_dir", "")).expanduser()
    root_name = cfg.text(config, "root_name", "")
    if "/" in root_name:
        raise cfg.bad("root_name", f"{root_name!r} holds a slash; it names the folder, it is not a path")
    identity = cfg.text(config, "identity", "")
    if identity not in MODES:
        raise cfg.bad("identity", f"{identity!r} is not one of {', '.join(MODES)}")
    zone_name = cfg.text(config, "zone", "")
    try:
        zone = zoneinfo.ZoneInfo(zone_name)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError) as exc:
        raise cfg.bad("zone", f"{zone_name!r} is not an IANA zone name") from exc
    # state_file has no default: an importer reads its source and does not write
    # into it, and nowhere else is the importer's to choose.
    state = Path(cfg.text(config, "state_file", "")).expanduser()
    if state.resolve() == links_dir.resolve() or links_dir.resolve() in state.resolve().parents:
        raise cfg.bad("state_file", f"{state} is under links_dir, which the importer reads and never writes")
    return Settings(links_dir, root_name, cfg.text(config, "person_id", ""), identity, zone,
                    cfg.integer(config, "unseen_after", DEFAULT_UNSEEN_AFTER, 1, 1000), state)


def media_type(path: Path) -> str:
    """By extension, a label on the name, not a verdict on the bytes: the same table
    the documents importer uses, so a file under either is labelled alike. Not
    configurable: another spelling supersedes every link that carries it."""
    known = {".pdf": "application/pdf", ".md": "text/markdown", ".markdown": "text/markdown", ".txt": "text/plain",
             ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
             ".webp": "image/webp", ".svg": "image/svg+xml", ".html": "text/html", ".htm": "text/html",
             ".json": "application/json", ".csv": "text/csv", ".xml": "text/xml", ".zip": "application/zip",
             ".tif": "image/tiff", ".tiff": "image/tiff", ".heic": "image/heic",
             ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
    ext = path.suffix.lower()
    if ext in known:
        return known[ext]
    guessed, _ = mimetypes.guess_type(path.name, strict=True)
    return guessed or "application/octet-stream"


def files(root: Path) -> List[Path]:
    """Every regular file under root in path order; dot-files, dot-directories and
    symlinks skipped, as the documents importer walks."""
    out: List[Path] = []
    for here, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        for name in names:
            p = Path(here) / name
            if name.startswith(".") or p.is_symlink() or not p.is_file():
                continue
            out.append(p)
    return sorted(out, key=lambda p: p.relative_to(root).as_posix())


def frontmatter(path: Path) -> Dict[str, Any]:
    """A Markdown file's YAML frontmatter as text values, or {} when it has none.
    Every scalar stays text, so a date or an id is read as the person wrote it."""
    import yaml

    with path.open("rb") as f:
        head = f.read(FRONT_READ).decode("utf-8", "replace")
    if not head.startswith("---\n") and not head.startswith("---\r\n"):
        return {}
    close = re.search(r"^(---|\.\.\.)[ \t]*\r?$", head[4:], re.M)
    if close is None:
        raise Skipped("frontmatter opens with --- and never closes", unread=True)

    class Loader(yaml.SafeLoader):
        pass

    Loader.yaml_implicit_resolvers = {}
    try:
        front = yaml.load(head[4:4 + close.start()], Loader=Loader)  # noqa: S506 (SafeLoader, resolving nothing)
    except yaml.YAMLError as exc:
        raise Skipped(f"frontmatter: {exc}", unread=True) from exc
    if front is None:
        return {}
    if not isinstance(front, dict):
        raise Skipped("frontmatter is not a mapping")
    return front


def read_date(text: str, zone: zoneinfo.ZoneInfo) -> Tuple[datetime, Dict[str, Any]]:
    """A date as a person writes one: YYYY-MM-DD, or that with a time, with or
    without an offset, and how it was read. No offset means the instance's zone; a
    bare date is midnight. A wall clock the zone skips or repeats names no one
    instant, and the file is left out until its date says which it means."""
    t = text.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError as exc:
        raise Skipped(f"frontmatter date {text!r} is not YYYY-MM-DD, with or without a time and offset") from exc
    if dt.tzinfo:
        written = "UTC" if text.strip().endswith("Z") else clk.offset_text(dt.utcoffset())
        return dt, clk.source_time(text.strip(), written, "source")
    return in_zone(dt, zone, f"frontmatter date {text!r}"), clk.source_time(text.strip(), zone.key, "configuration")


def in_zone(wall: datetime, zone: zoneinfo.ZoneInfo, what: str) -> datetime:
    """wall read in zone, the instance's zone key. One the zone skips or repeats is
    left out, and unread, so the run claims no snapshot without it."""
    try:
        return clk.local_instant(wall, zone.key)
    except clk.ClockError as exc:
        raise Skipped(f"{what}: {exc}", unread=True) from exc


def exif_original(path: Path) -> Optional[Tuple[str, Optional[str]]]:
    """DateTimeOriginal and OffsetTimeOriginal as a JPEG's or a TIFF's EXIF holds them,
    or None. A reader of the few bytes needed, not an image library: the APP1 segment
    of a JPEG, or the first EXIF_READ of a TIFF, is walked IFD0 then the Exif IFD."""
    try:
        with path.open("rb") as f:
            head = f.read(4)
            if head[:2] == b"\xff\xd8":
                tiff = _jpeg_app1(f)
            elif head in (b"II*\x00", b"MM\x00*"):
                f.seek(0)
                tiff = f.read(EXIF_READ)
            else:
                return None
    except OSError:
        return None
    if not tiff or tiff[:2] not in (b"II", b"MM"):
        return None
    order = "<" if tiff[:2] == b"II" else ">"
    try:
        ifd0 = struct.unpack(order + "I", tiff[4:8])[0]
        pointer = _entries(tiff, order, ifd0).get(0x8769)
        if pointer is None or pointer[0] != 4:
            return None
        exif = _entries(tiff, order, struct.unpack(order + "I", pointer[2][:4])[0])
        taken = _ascii(tiff, order, exif.get(0x9003))
        return (taken, _ascii(tiff, order, exif.get(0x9011))) if taken else None
    except (struct.error, IndexError):
        return None


def _jpeg_app1(f: BinaryIO) -> Optional[bytes]:
    """The TIFF block of a JPEG's EXIF APP1 segment, or None by the first scan."""
    f.seek(2)
    while True:
        marker = f.read(2)
        if len(marker) < 2 or marker[0] != 0xFF or marker[1] in (0xD9, 0xDA):
            return None
        if marker[1] in (0x01, 0xFF) or 0xD0 <= marker[1] <= 0xD7:
            f.seek(-1 if marker[1] == 0xFF else 0, 1)
            continue
        length = struct.unpack(">H", f.read(2))[0] - 2
        if marker[1] == 0xE1:
            data = f.read(length)
            if data.startswith(b"Exif\x00\x00"):
                return data[6:]
            continue
        f.seek(length, 1)


def _entries(tiff: bytes, order: str, offset: int) -> Dict[int, Tuple[int, int, bytes]]:
    """An IFD's entries by tag: type, count and the four value-or-offset bytes."""
    n = struct.unpack(order + "H", tiff[offset:offset + 2])[0]
    out = {}
    for i in range(n):
        at = offset + 2 + 12 * i
        tag, typ, count = struct.unpack(order + "HHI", tiff[at:at + 8])
        out[tag] = (typ, count, tiff[at + 8:at + 12])
    return out


def _ascii(tiff: bytes, order: str, entry: Optional[Tuple[int, int, bytes]]) -> Optional[str]:
    """An ASCII entry's text, or None when it is absent or not ASCII."""
    if entry is None or entry[0] != 2:
        return None
    typ, count, raw = entry
    if count > 4:
        off = struct.unpack(order + "I", raw)[0]
        raw = tiff[off:off + count]
    text = raw[:count].split(b"\x00")[0].decode("ascii", "replace").strip()
    return text or None


def fact_time(path: Path, front: Dict[str, Any], zone: zoneinfo.ZoneInfo) -> Tuple[str, str, Dict[str, Any]]:
    """The file's date as RFC 3339 with an offset, which source answered, and how
    its clock was read (anam card 198): an offset written with the date is the
    source's, the instance's zone key is configuration, and mtime is an epoch, UTC."""
    if "date" in front:
        if not isinstance(front["date"], str) or not front["date"].strip():
            raise Skipped("frontmatter date is not text")
        when, how = read_date(front["date"], zone)
        return when.isoformat(timespec="seconds"), "frontmatter", how
    if path.suffix.lower() in EXIF_KINDS:
        found = exif_original(path)
        if found:
            try:
                taken = datetime.strptime(found[0], "%Y:%m:%d %H:%M:%S")
                offset = datetime.strptime(found[1], "%z").utcoffset() if found[1] else None
            except ValueError:
                offset, taken = None, None  # a camera that wrote something else: the next source answers
            if taken is not None and offset is not None:
                written = clk.offset_text(offset)
                return (clk.at_offset(taken.replace(tzinfo=timezone(offset)), offset), "exif",
                        clk.source_time(found[0], written, "source"))
            if taken is not None:
                when = in_zone(taken, zone, f"EXIF DateTimeOriginal {found[0]!r}")
                return when.isoformat(timespec="seconds"), "exif", clk.source_time(found[0], zone.key, "configuration")
    m = FILENAME_DATE.match(path.name)
    if m:
        try:
            day = datetime(int(m[1]), int(m[2]), int(m[3]))
        except ValueError:
            day = None  # 2024-13-45 is a name, not a date
        if day is not None:
            when = in_zone(day, zone, f"the name's date {m[0]}")
            return when.isoformat(timespec="seconds"), "filename", clk.source_time(m[0], zone.key, "configuration")
    if path.suffix.lower() in MARKDOWN:
        raise Skipped("no date: write `date:` in its frontmatter or prefix the name with YYYY-MM-DD "
                      "(mtime is refused for Markdown, since every edit would move the fact)")
    seconds = int(path.stat().st_mtime)
    mtime = datetime.fromtimestamp(seconds, tz=zone)
    # A modification time is an epoch, UTC by the filesystem's definition; the
    # zone key only chooses the offset date is written at.
    return mtime.isoformat(timespec="seconds"), "mtime", clk.source_time(str(seconds), "UTC", "source")


def describe(s: Settings, path: Path) -> Dict[str, Any]:
    """One file as its payload. Raises Skipped for a file this instance cannot send."""
    rel = path.relative_to(s.links_dir).as_posix()
    front = frontmatter(path) if path.suffix.lower() in MARKDOWN else {}
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
            size += len(chunk)
    date, date_from, how = fact_time(path, front, s.zone)
    payload: Dict[str, Any] = {"identity": s.identity, "root": s.root_name, "path": rel, "sha256": h.hexdigest(),
                               "bytes": size, "media_type": media_type(path), "date": date, "date_from": date_from,
                               "source_time": how}
    if s.identity == "path":
        payload["id"] = f"path:{s.root_name}/{rel}"
    elif s.identity == "content":
        payload["id"] = f"content:{payload['sha256']}"
    else:
        declared = front.get("id")
        if not isinstance(declared, str) or not declared.strip():
            raise Skipped("no id in its frontmatter, and this instance keys on a declared id")
        payload["id"] = f"id:{declared.strip()}"
    if isinstance(front.get("title"), str) and front["title"].strip():
        payload["title"] = front["title"]
    return payload


@dataclass
class Scan:
    """What one walk of links_dir found: payloads by id in path order, the skipped
    files with why, how many went unread, and how many are dated by mtime."""

    seen: Dict[str, Dict[str, Any]]
    skipped: List[str]
    unread: int
    weak: int


def scan(s: Settings) -> Scan:
    """Every file under links_dir. An unreachable links_dir is no run."""
    if not s.links_dir.is_dir():
        raise ductile.Failure(f"links_dir {s.links_dir} is not reachable; no run", retry=True)
    out = Scan({}, [], 0, 0)
    by_id_path: Dict[str, str] = {}
    for p in files(s.links_dir):
        rel = p.relative_to(s.links_dir).as_posix()
        try:
            payload = describe(s, p)
            if payload["id"] in out.seen:
                raise Skipped(f"its id {payload['id']} is also {by_id_path[payload['id']]}'s; the first by path is sent")
        except Skipped as exc:
            out.skipped.append(f"skipped {rel}: {exc}")
            out.unread += exc.unread
            continue
        except OSError as exc:
            out.skipped.append(f"skipped {rel}: cannot read it ({exc.strerror or exc})")
            out.unread += 1
            continue
        out.seen[payload["id"]] = payload
        by_id_path[payload["id"]] = rel
        out.weak += payload["date_from"] == "mtime"
    return out


def load_state(path: Path) -> Dict[str, Dict[str, Any]]:
    """The known files by id: the payload last sent as seen, when it was last seen,
    how many complete runs have missed it, and since when."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise ductile.Failure(f"state_file {path}: {exc}", retry=True) from exc
    try:
        state = json.loads(text)
        if state.get("version") != STATE_VERSION or not isinstance(state.get("known"), dict):
            raise ValueError("not a version 1 state")
        return state["known"]
    except ValueError as exc:
        raise ductile.Failure(f"state_file {path}: {exc}; move it aside to start the count again", retry=False) from exc


def save_state(path: Path, known: Dict[str, Dict[str, Any]]) -> None:
    """known, written whole then renamed into place, so a crash leaves the old file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"version": STATE_VERSION, "known": known}, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise ductile.Failure(f"state_file {path}: {exc}; set state_file to a writable path", retry=False) from exc


def reconcile(known: Dict[str, Dict[str, Any]], seen: Dict[str, Dict[str, Any]], now: str,
              unseen_after: int) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]], int]:
    """The state after this run and every payload the run stands behind: each seen
    file as observed, each known file not seen as it was until unseen_after runs have
    missed it, then with unseen. Also how many are unseen. Nothing is dropped: the
    run is a snapshot, and a file the importer last saw is still its fact."""
    out: Dict[str, Dict[str, Any]] = {}
    payloads: List[Dict[str, Any]] = []
    unseen = 0
    for fid, payload in seen.items():
        out[fid] = {"payload": payload, "last_seen": now, "misses": 0}
        payloads.append(payload)
    for fid, entry in known.items():
        if fid in seen:
            continue
        misses = int(entry.get("misses", 0)) + 1
        kept = {"payload": entry["payload"], "last_seen": entry["last_seen"], "misses": misses,
                "unseen_since": entry.get("unseen_since") or now}
        out[fid] = kept
        payload = dict(entry["payload"])
        if "source_time" not in payload:
            payload["source_time"] = remembered(payload["date"])
        if misses >= unseen_after:
            payload.update({"unseen": True, "unseen_since": kept["unseen_since"], "last_seen": kept["last_seen"]})
            unseen += 1
        payloads.append(payload)
    return out, payloads, unseen


def remembered(date: str) -> Dict[str, Any]:
    """How the date of a file last seen before record.link v2 was read, which the
    state file did not keep: date is RFC 3339 with its offset, and that offset is all
    that is known of its zone, so the basis is an assumption (anam card 198)."""
    return clk.source_time(date, clk.zone_written(date), "assumption")


def assumed(payloads: List[Dict[str, Any]]) -> List[str]:
    """A log line for the files whose date's zone is an assumption."""
    n = sum(1 for p in payloads if p["source_time"]["basis"] == "assumption")
    if not n:
        return []
    return [f"{n} unseen file(s) last seen before source_time: their date keeps its own offset (basis assumption)"]


def envelopes_of(definition: Definition, payloads: List[Dict[str, Any]], person: str) -> List[Dict[str, Any]]:
    return [envelope(definition, p, asserted_person=person) for p in payloads]


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    s = settings(request.get("config") or {})
    definitions = load(HERE)
    definition = definitions[TYPE]
    known = load_state(s.state_file)
    found = scan(s)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    known, payloads, unseen = reconcile(known, found.seen, now, s.unseen_after)
    envs = envelopes_of(definition, payloads, s.person)
    check(definitions, envs)
    save_state(s.state_file, known)
    groups = list(batches(envs))
    manifests = definitions.manifests()
    events = [ductile.event(BATCH_EVENT, {"envelopes": g, "definitions": manifests, "batch": f"links {i + 1}/{len(groups)}"})
              for i, g in enumerate(groups)]
    # Everything the importer stands behind, seen or unseen, so the run is a snapshot,
    # unless a file went unread: Anam must not call its facet absent for that.
    if not found.unread:
        for ev, part in zip(events, snapshot_parts(len(events), [TYPE])):
            ev["payload"]["snapshot"] = part
    logs = found.skipped + assumed(payloads)
    if found.weak:
        logs.append(f"{found.weak} file(s) dated by mtime, which every edit moves")
    summary = f"{len(found.seen)} file(s) seen, {unseen} unseen, {len(found.skipped)} skipped, in {len(events)} batch(es)"
    if found.unread:
        summary += f"; no snapshot: {found.unread} file(s) could not be read"
    return ductile.ok(summary, events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    return poll(request)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    s = settings(request.get("config") or {})
    definitions = load(HERE)
    known = load_state(s.state_file)
    found = scan(s)
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _, payloads, unseen = reconcile(known, found.seen, now, s.unseen_after)
    check(definitions, envelopes_of(definitions[TYPE], payloads, "health-check"))
    logs = found.skipped + assumed(payloads)
    if found.weak:
        logs.append(f"{found.weak} file(s) dated by mtime, which every edit moves")
    return ductile.ok(f"{len(found.seen)} file(s) under {s.links_dir}, keyed by {s.identity}; {len(known)} known, "
                      f"{unseen} unseen past {s.unseen_after} run(s); {len(found.skipped)} skipped, "
                      f"{found.unread} unread; {found.weak} on mtime (weak)", logs=logs)


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
