#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18", "garmin-fit-sdk==21.218.0"]
# ///
"""anam_garmin: shapes what a Garmin watch recorded into Anam envelopes, one batch
event at a time.

Today that is the abnormal high heart rate alert, read straight from the watch's
monitoring FIT files under GarminDB's FitFiles/Monitoring. GarminDB downloads
those files but drops their event messages on import, so nothing else holds the
alert. This is the health ETL's fit_events.py (ductile-healthdata), moved: the same
event decoded the same way, and the same payload the health-db worker built from
the ETL's events table. It keeps no state of its own: Anam makes a resend a no-op.

Commands:
- handle : after a GarminDB sync, the FIT files changed in the last lookback_days
- poll   : every FIT file under fit_dir, in batches: the resend-everything mode
- health : fit_dir is readable and every alert in it conforms
"""

from __future__ import annotations

import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402

ALERT_TYPE = "health.heart-rate-alert"
BATCH_EVENT = "anam_garmin.batch"

# HR_HIGH_ALERT is the FIT event number the watch writes for an abnormal high
# heart rate alert. Garmin does not document it; it was read from Matt's watch.
HR_HIGH_ALERT = 66

# DEFAULT_LOOKBACK_DAYS bounds handle to the files a sync can have touched. A
# monitoring file covers one day and the watch syncs at least daily.
DEFAULT_LOOKBACK_DAYS = 3


def number(v: float) -> Any:
    """v as JSON writes a whole number: 117, not 117.0."""
    return int(v) if float(v).is_integer() else v


def alert(mesg: Dict[str, Any]) -> Dict[str, Any]:
    """One alert, as the health-db worker built it from the ETL's events row. The
    event's 16-bit data packs the heart rate that tripped the alert in the high byte
    and the threshold configured on the watch in the low byte."""
    data = int(mesg["data"])
    ts: datetime = mesg["timestamp"]
    return {
        "source": "garmin",
        "kind": "hr_high_alert",
        "fact_time": ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "heart_rate": number(data >> 8),
        "threshold": number(data & 0xFF),
        "unit": "bpm",
    }


def alerts_in(path: Path) -> List[Dict[str, Any]]:
    """The alerts in one FIT file. A file the SDK cannot decode is a failure."""
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError as exc:
        raise ductile.Failure(f"the garmin-fit-sdk package is not installed: {exc}", retry=False) from exc
    try:
        msgs, errors = Decoder(Stream.from_file(str(path))).read(convert_types_to_strings=True)
    except OSError as exc:
        raise ductile.Failure(f"FIT file {path}: {exc}", retry=True) from exc
    if errors:
        raise ValueError("; ".join(str(e) for e in errors))
    return [alert(m) for m in msgs.get("event_mesgs", [])
            if m.get("event") == HR_HIGH_ALERT and m.get("timestamp") is not None and m.get("data") is not None]


def fit_files(config: Dict[str, Any], since: Optional[float] = None) -> List[Path]:
    """The FIT files under fit_dir, oldest name first; with since, only those
    modified at or after it."""
    root = Path(str(config["fit_dir"]))
    if not root.is_dir():
        raise ductile.Failure(f"no fit_dir at {root}", retry=False)
    files = sorted(p for p in root.rglob("*.fit") if p.is_file())
    if since is not None:
        files = [p for p in files if p.stat().st_mtime >= since]
    return files


def alerts(files: List[Path]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every alert in files, once each, ordered by fact_time, and a log line per
    file that would not decode. The same alert in two files is one alert: the first
    file by name keeps it, as the ETL's INSERT OR IGNORE did."""
    seen: Dict[str, Dict[str, Any]] = {}
    logs: List[str] = []
    for path in files:
        try:
            found = alerts_in(path)
        except ValueError as exc:
            logs.append(f"skipped {path.name}: {exc}")
            continue
        for a in found:
            seen.setdefault(a["fact_time"], a)
    return [seen[k] for k in sorted(seen)], logs


def batch_events(definitions: Dict[str, Definition], payloads: List[Dict[str, Any]], person: str,
                 snapshot: bool) -> List[Dict[str, Any]]:
    definition = definitions[ALERT_TYPE]
    envs = [envelope(definition, p, asserted_person=person) for p in payloads]
    check(definitions, envs)
    groups = list(batches(envs))
    manifest = definition.body.decode()
    parts = snapshot_parts(len(groups), [ALERT_TYPE]) if snapshot and groups else [None] * len(groups)
    events = []
    for i, (g, part) in enumerate(zip(groups, parts)):
        payload: Dict[str, Any] = {"envelopes": g, "definitions": [manifest], "batch": f"{i + 1}/{len(groups)}"}
        if part is not None:
            payload["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, payload))
    return events


def run_over(config: Dict[str, Any], files: List[Path], snapshot: bool) -> Dict[str, Any]:
    payloads, logs = alerts(files)
    # A file that would not decode leaves its alerts out, so the run is not everything.
    events = batch_events(load(HERE), payloads, str(config["person_id"]), snapshot and not logs)
    return ductile.ok(f"{len(payloads)} alert(s) in {len(files)} FIT file(s), {len(events)} batch(es)",
                      events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    days = float(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    return run_over(config, fit_files(config, since=time.time() - days * 86400), snapshot=False)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    # Every monitoring file the watch has given GarminDB is every alert, so poll's run
    # is a snapshot, unless a file would not decode.
    return run_over(config, fit_files(config), snapshot=True)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    files = fit_files(config)
    payloads, logs = alerts(files)
    check(definitions, [envelope(definitions[ALERT_TYPE], p) for p in payloads])
    if logs:
        return ductile.error(f"{len(logs)} of {len(files)} FIT file(s) would not decode", retry=False, logs=logs)
    return ductile.ok(f"{len(payloads)} alert(s) in {len(files)} FIT file(s), every one conforming to "
                      f"{ALERT_TYPE} v{definitions[ALERT_TYPE].version}")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
