#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18"]
# ///
"""anam_owntracks: shapes the positions OwnTracks reported into Anam envelopes, one
location.track per phone per UTC hour, one batch event at a time.

The phone posts each fix to a receiver at the edge, and the gateway's owntracks plugin
pulls what the receiver holds into a spool: one JSON line per message, under
<spool_dir>/<device>/<YYYY-MM>.jsonl, the body exactly as the phone posted it. The
spool is the source. This importer reads it and never touches the network; it keeps
no state of its own, and Anam makes a resend a no-op.

An hour is sent whole, every point in it, because its facet replaces the last one
sent. So handle reads the whole spool and sends the hours that gained a message in
the last lookback_days, not just the new messages.

Positions never leave the payload: no coordinates in a log line, a result or an
event's name. Logs carry counts, file names and line numbers only.

Commands:
- handle : after a pull, the hours that gained messages in the last lookback_days
- poll   : every hour the spool holds, in batches: the resend-everything mode
- health : the spool is readable and every hour in it conforms
"""

from __future__ import annotations

import json
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

TRACK_TYPE = "location.track"
BATCH_EVENT = "anam_owntracks.batch"

# DEFAULT_LOOKBACK_DAYS bounds handle to the hours a pull can have touched, unless
# config's lookback_days says otherwise. The pull runs every 15 minutes; a phone
# offline for a day sends its queue when it is back, and those messages are received
# now, so they count as new however old their fixes.
DEFAULT_LOOKBACK_DAYS = 2

# DEFAULT_MAX_PAYLOAD is the gate's bound on one payload (300 KiB in Anam's gate),
# less room for the envelope, unless config's max_payload_bytes says otherwise. An
# hour over it would be refused whole; at OwnTracks' densest it is far under. Anam
# holds the bound as policy, so an Anam run with another one takes another value here.
DEFAULT_MAX_PAYLOAD = 290 * 1024


class Settings(NamedTuple):
    """This run's config, read and checked once, at the start of a command."""

    lookback_days: float
    max_payload: int


def settings(config: Dict[str, Any]) -> Settings:
    return Settings(
        lookback_days=cfg.number(config, "lookback_days", DEFAULT_LOOKBACK_DAYS, 0, 3650, low_open=True),
        max_payload=cfg.integer(config, "max_payload_bytes", DEFAULT_MAX_PAYLOAD, 1, 64 << 20),
    )

# FIELDS maps the body's keys a point keeps to the Definition's names. The phone's
# own names are kept where they are plain; the two upper-case WiFi keys are lowered,
# and m, source and t are spelled out.
FIELDS = {"lat": "lat", "lon": "lon", "acc": "acc", "alt": "alt", "vac": "vac", "vel": "vel", "cog": "cog",
          "batt": "batt", "bs": "bs", "conn": "conn", "SSID": "ssid", "BSSID": "bssid", "inregions": "inregions",
          "m": "monitoring", "source": "location_source", "tid": "tid"}
NUMBERS = {"lat", "lon", "acc", "alt", "vac", "vel", "cog"}
INTEGERS = {"batt", "bs", "m"}
STRINGS = {"conn", "SSID", "BSSID", "source", "tid"}

# TRANSPORT is what a body carries about the message rather than the fix: dropped
# without remark. tst and t are read into the point as its time and its triggers.
TRANSPORT = {"_type", "_id", "topic", "qos", "retained", "created_at", "tst", "t"}

# FIX_KEYS are what make two messages with one tst the same fix. A second message
# that differs in them is counted and dropped; the first received wins. Not
# configurable: it decides which points an hour's facet holds.
FIX_KEYS = ("lat", "lon", "acc")


def number(v: float) -> Any:
    """v as JSON writes a whole number: 14, not 14.0."""
    return int(v) if float(v).is_integer() else v


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def instant(tst: int) -> str:
    return datetime.fromtimestamp(tst, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def hour_of(tst: int) -> str:
    """The UTC hour tst falls in. Not configurable: an hour is a facet's identity."""
    return datetime.fromtimestamp(tst - tst % 3600, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def point(body: Dict[str, Any], unknown: Counter) -> Dict[str, Any]:
    """One location body as a point. A field of the wrong kind is left out; a field
    the Definition does not know is counted in unknown and left out. A body without
    a time or coordinates is a ValueError."""
    tst, lat, lon = body.get("tst"), body.get("lat"), body.get("lon")
    if not isinstance(tst, int) or isinstance(tst, bool) or tst <= 0:
        raise ValueError("no tst")
    if not is_number(lat) or not is_number(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("no coordinates")
    p: Dict[str, Any] = {"t": instant(tst)}
    for key, name in FIELDS.items():
        v = body.get(key)
        if key in NUMBERS and is_number(v):
            p[name] = number(v)
        elif key in INTEGERS and isinstance(v, int) and not isinstance(v, bool):
            p[name] = v
        elif key in STRINGS and isinstance(v, str) and v:
            p[name] = v
        elif key == "inregions" and isinstance(v, list) and all(isinstance(r, str) for r in v):
            p[name] = list(v)
    for name in ("acc", "vac", "vel"):
        if name in p and p[name] < 0:
            del p[name]  # OwnTracks writes -1 or less for "not known"
    if not 0 <= p.get("batt", 0) <= 100:
        del p["batt"]
    if not 0 <= p.get("bs", 0) <= 3:
        del p["bs"]
    if isinstance(body.get("t"), str) and body["t"]:
        p["triggers"] = [body["t"]]
    unknown.update(k for k in body if k not in FIELDS and k not in TRANSPORT)
    return p


@dataclass
class Hour:
    """One phone's hour: its points by fix time, and the newest receipt among them."""

    device: str
    hour: str
    points: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    received: int = 0

    def add(self, tst: int, p: Dict[str, Any], received: int, conflicts: Counter) -> None:
        self.received = max(self.received, received)
        held = self.points.get(tst)
        if held is None:
            self.points[tst] = p
            return
        if any(held.get(k) != p.get(k) for k in FIX_KEYS):
            conflicts[self.device] += 1
            return
        for t in p.get("triggers", []):
            if t not in held.setdefault("triggers", []):
                held["triggers"].append(t)

    def payload(self) -> Dict[str, Any]:
        return {"id": f"loc:{self.device}:{self.hour}", "hour": self.hour, "device": self.device,
                "points": [self.points[k] for k in sorted(self.points)]}


@dataclass
class Read:
    """What a read of the spool found: the hours, and what it could not use."""

    hours: Dict[Tuple[str, str], Hour] = field(default_factory=dict)
    lines: int = 0
    kinds: Counter = field(default_factory=Counter)
    unknown: Counter = field(default_factory=Counter)
    conflicts: Counter = field(default_factory=Counter)
    bad: List[str] = field(default_factory=list)

    def logs(self) -> List[str]:
        out = list(self.bad)
        skipped = {k: n for k, n in self.kinds.items() if k != "location"}
        if skipped:
            out.append("skipped messages that are not locations: " + ", ".join(f"{k} {n}" for k, n in sorted(skipped.items())))
        if self.unknown:
            out.append("body fields the Definition does not keep: " + ", ".join(f"{k} {n}" for k, n in sorted(self.unknown.items())))
        if self.conflicts:
            out.append("messages dropped for sharing a fix time with a different fix: "
                       + ", ".join(f"{d} {n}" for d, n in sorted(self.conflicts.items())))
        return out


def spool_dir(config: Dict[str, Any]) -> Path:
    root = Path(str(config["spool_dir"]))
    if not root.is_dir():
        raise ductile.Failure(f"no spool_dir at {root}", retry=False)
    return root


def spool_files(root: Path) -> List[Path]:
    return sorted(p for p in root.glob("*/*.jsonl") if p.is_file())


def lines_of(path: Path) -> Iterator[Tuple[int, str]]:
    """Each complete line of a spool file, numbered from 1. A last line without its
    newline is a pull still appending, or torn by a crash the pull will repair: not
    yet a line."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        raise ductile.Failure(f"{path.name} went while the run read it", retry=True) from None
    text = data.decode("utf-8", "replace")
    parts = text.split("\n")
    for i, line in enumerate(parts[:-1]):
        if line.strip():
            yield i + 1, line


def read_spool(root: Path) -> Read:
    """Every location in the spool, as hours. Messages are taken in the receiver's
    id order, so the first received of a fix's messages is the one kept."""
    out = Read()
    rows: List[Tuple[int, str, Dict[str, Any]]] = []
    for path in spool_files(root):
        device = path.parent.name
        where = f"{device}/{path.name}"
        for n, line in lines_of(path):
            out.lines += 1
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("id"), int) or not isinstance(row.get("body"), str):
                    raise ValueError("not a spool line")
            except ValueError as exc:
                out.bad.append(f"skipped {where} line {n}: {exc.__class__.__name__}")
                continue
            rows.append((row["id"], where, {**row, "_line": n, "_device": device}))
    rows.sort(key=lambda r: r[0])
    for _, where, row in rows:
        if not row["body"].strip():
            out.kinds["empty"] += 1
            continue
        try:
            body = json.loads(row["body"])
        except ValueError:
            out.bad.append(f"skipped {where} line {row['_line']}: the body is not JSON")
            continue
        kind = body.get("_type") if isinstance(body, dict) else None
        out.kinds[kind if isinstance(kind, str) else "untyped"] += 1
        if kind != "location":
            continue
        try:
            p = point(body, out.unknown)
        except ValueError as exc:
            out.bad.append(f"skipped {where} line {row['_line']}: {exc}")
            continue
        device = row["_device"]
        key = (device, hour_of(body["tst"]))
        h = out.hours.setdefault(key, Hour(device, key[1]))
        received = row.get("received_at")
        h.add(body["tst"], p, received if isinstance(received, int) else 0, out.conflicts)
    return out


def batch_events(payloads: List[Dict[str, Any]], person: str, snapshot: bool) -> List[Dict[str, Any]]:
    definition = load(HERE)[TRACK_TYPE]
    envs = [envelope(definition, p, asserted_person=person) for p in payloads]
    check({TRACK_TYPE: definition}, envs)
    groups = list(batches(envs))
    parts = snapshot_parts(len(groups), [TRACK_TYPE]) if snapshot and groups else [None] * len(groups)
    events = []
    for i, (g, part) in enumerate(zip(groups, parts)):
        payload: Dict[str, Any] = {"envelopes": g, "definitions": [definition.body.decode()],
                                   "batch": f"{TRACK_TYPE} {i + 1}/{len(groups)}"}
        if part is not None:
            payload["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, payload))
    return events


def sized(hours: List[Hour], max_payload: int, logs: List[str]) -> List[Dict[str, Any]]:
    """The hours' payloads, oldest first, less any over max_payload bytes."""
    out = []
    for h in sorted(hours, key=lambda h: (h.hour, h.device)):
        p = h.payload()
        size = len(json.dumps(p, separators=(",", ":")))
        if size > max_payload:
            logs.append(f"skipped {h.device} {h.hour}: {len(p['points'])} points, {size} bytes, over {max_payload}")
            continue
        out.append(p)
    return out


def run_over(config: Dict[str, Any], s: Settings, since: Optional[float]) -> Dict[str, Any]:
    read = read_spool(spool_dir(config))
    hours = list(read.hours.values())
    if since is not None:
        hours = [h for h in hours if h.received >= since]
    logs = read.logs()
    payloads = sized(hours, s.max_payload, logs)
    # A line or an hour that could not be used leaves points out, so the run is not
    # everything. Messages that are not locations, unknown fields and duplicate
    # fixes are the source as it is, and leave nothing out.
    whole = not read.bad and len(payloads) == len(hours)
    events = batch_events(payloads, str(config["person_id"]), since is None and whole)
    points = sum(len(p["points"]) for p in payloads)
    return ductile.ok(f"{len(payloads)} hour(s), {points} point(s) from {read.lines} spool line(s), {len(events)} batch(es)",
                      events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    return run_over(config, s, time.time() - s.lookback_days * 86400)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    # The spool keeps every message ever pulled, so poll's run is a snapshot, unless
    # a line would not read.
    return run_over(config, settings(config), None)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    read = read_spool(spool_dir(config))
    logs = read.logs()
    payloads = sized(list(read.hours.values()), s.max_payload, logs)
    definition = load(HERE)[TRACK_TYPE]
    check({TRACK_TYPE: definition}, [envelope(definition, p) for p in payloads])
    if read.bad or len(payloads) != len(read.hours):
        unusable = len(read.bad) + len(read.hours) - len(payloads)
        return ductile.error(f"{unusable} spool line(s) or hour(s) would not shape", retry=False, logs=logs)
    return ductile.ok(f"{len(payloads)} {TRACK_TYPE} v{definition.version} hour(s) from {read.lines} spool line(s), "
                      "every one conforming", logs=logs)


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
