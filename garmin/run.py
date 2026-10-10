#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18", "garmin-fit-sdk==21.218.0"]
# ///
"""anam_garmin: shapes what a Garmin watch recorded into Anam envelopes, one batch
event at a time.

Two things today. The abnormal high heart rate alert, read straight from the
watch's monitoring FIT files under GarminDB's FitFiles/Monitoring: GarminDB
downloads those files but drops their event messages on import, so nothing else
holds the alert. This is the health ETL's fit_events.py (ductile-healthdata),
moved: the same event decoded the same way, and the same payload the health-db
worker built from the ETL's events table. And each night's sleep, from GarminDB's
garmin.db sleep table, as a sleep.episode: the IEEE 1752 body with Garmin's score
and averages beside it. It keeps no state of its own: Anam makes a resend a no-op.

Commands:
- handle : after a GarminDB sync, what changed in the last lookback_days
- poll   : everything, in batches: the resend-everything mode
- health : the sources are readable and everything in them conforms
"""

from __future__ import annotations

import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402

ALERT_TYPE = "health.heart-rate-alert"
SLEEP_TYPE = "sleep.episode"
HEART_TYPE = "health.heart-rate-daily"

# ZONE is where Garmin's days are local days.
ZONE = ZoneInfo("Australia/Sydney")
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


def minutes(t: str) -> Any:
    """GarminDB's TIME text, "05:49:00.000000", as minutes: 349."""
    h, m, sec = t.split(":")
    return number(int(h) * 60 + int(m) + float(sec) / 60)


def instant(t: str) -> str:
    """GarminDB's UTC DATETIME text, "2026-10-07 12:44:00.000000", as RFC 3339."""
    return datetime.fromisoformat(t).replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sleep_episode(row: sqlite3.Row) -> Dict[str, Any]:
    """One night of Garmin's sleep table as a sleep.episode payload."""
    p: Dict[str, Any] = {
        "id": row["day"],
        "effective_time_frame": {"time_interval": {"start_date_time": instant(row["start"]),
                                                   "end_date_time": instant(row["end"])}},
        "total_sleep_time": {"value": minutes(row["total_sleep"]), "unit": "min"},
        "light_sleep_duration": {"value": minutes(row["light_sleep"]), "unit": "min"},
        "deep_sleep_duration": {"value": minutes(row["deep_sleep"]), "unit": "min"},
        "rem_sleep_duration": {"value": minutes(row["rem_sleep"]), "unit": "min"},
        "wake_after_sleep_onset": {"value": minutes(row["awake"]), "unit": "min"},
        "is_main_sleep": True,
    }
    for key in ("score", "qualifier"):
        if row[key] not in (None, ""):
            p[key] = row[key]
    for key in ("avg_spo2", "avg_rr", "avg_stress"):
        if row[key] is not None:
            p[key] = number(row[key])
    return p


def sleeps(config: Dict[str, Any], since: Optional[date] = None) -> List[Dict[str, Any]]:
    """Every night garmin.db's sleep table holds, by day; with since, those from that
    day on. A day without a start is a day the watch saw no sleep: no episode."""
    rows = query(config, 'SELECT day, start, "end", total_sleep, deep_sleep, light_sleep, rem_sleep, awake, '
                         "avg_spo2, avg_rr, avg_stress, score, qualifier FROM sleep "
                         'WHERE start IS NOT NULL AND "end" IS NOT NULL AND day >= ? ORDER BY day', since)
    return [sleep_episode(r) for r in rows]


def query(config: Dict[str, Any], sql: str, since: Optional[date]) -> List[sqlite3.Row]:
    """sql's rows from garmin_db, opened read-only; its one parameter is the first
    day wanted."""
    path = Path(str(config["garmin_db"]))
    if not path.is_file():
        raise ductile.Failure(f"no garmin_db at {path}", retry=False)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, ((since or date.min).isoformat(),)).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        raise ductile.Failure(f"garmin_db {path}: {exc}", retry=True) from exc


def day_frame(day: str) -> Dict[str, Any]:
    """A Garmin day as an OMH time interval: local midnight to the next."""
    start = datetime.combine(date.fromisoformat(day), clock(0), ZONE)
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), clock(0), ZONE)
    return {"time_interval": {"start_date_time": start.isoformat(), "end_date_time": end.isoformat()}}


def heart_figure(day: str, statistic: str, bpm: float) -> Dict[str, Any]:
    p: Dict[str, Any] = {"id": day, "statistic": statistic,
                         "heart_rate": {"value": number(bpm), "unit": "beats/min"},
                         "effective_time_frame": day_frame(day)}
    if statistic == "resting":
        p["temporal_relationship_to_physical_activity"] = "at rest"
    else:
        p["descriptive_statistic"] = statistic
    return p


def heart_rates(config: Dict[str, Any], since: Optional[date] = None) -> List[Dict[str, Any]]:
    """Each day's resting heart rate (resting_hr) and its minimum and maximum
    (daily_summary), by day. A figure Garmin left empty is no facet."""
    figures = [heart_figure(r["day"], "resting", r["resting_heart_rate"])
               for r in query(config, "SELECT day, resting_heart_rate FROM resting_hr "
                                      "WHERE resting_heart_rate IS NOT NULL AND day >= ?", since)]
    for r in query(config, "SELECT day, hr_min, hr_max FROM daily_summary WHERE day >= ?", since):
        figures += [heart_figure(r["day"], stat, r[col]) for stat, col in (("minimum", "hr_min"), ("maximum", "hr_max"))
                    if r[col] is not None]
    order = {"resting": 0, "minimum": 1, "maximum": 2}
    return sorted(figures, key=lambda f: (f["id"], order[f["statistic"]]))


def batch_events(definitions: Dict[str, Definition], by_type: Dict[str, List[Dict[str, Any]]], person: str,
                 snapshot: bool) -> List[Dict[str, Any]]:
    """Each type's payloads in batches of their own, labelled one snapshot across
    them all when snapshot is set."""
    shaped = []
    for typ, payloads in by_type.items():
        definition = definitions[typ]
        envs = [envelope(definition, p, asserted_person=person) for p in payloads]
        check(definitions, envs)
        groups = list(batches(envs))
        shaped += [(definition, g, f"{typ} {i + 1}/{len(groups)}") for i, g in enumerate(groups)]
    parts = snapshot_parts(len(shaped), list(by_type)) if snapshot and shaped else [None] * len(shaped)
    events = []
    for (definition, g, label), part in zip(shaped, parts):
        payload: Dict[str, Any] = {"envelopes": g, "definitions": [definition.body.decode()], "batch": label}
        if part is not None:
            payload["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, payload))
    return events


def run_over(config: Dict[str, Any], files: List[Path], since: Optional[date], snapshot: bool) -> Dict[str, Any]:
    found, logs = alerts(files)
    nights = sleeps(config, since)
    hearts = heart_rates(config, since)
    # A file that would not decode leaves its alerts out, so the run is not everything.
    by_type = {ALERT_TYPE: found, SLEEP_TYPE: nights, HEART_TYPE: hearts}
    events = batch_events(load(HERE), by_type, str(config["person_id"]), snapshot and not logs)
    return ductile.ok(f"{len(found)} alert(s) in {len(files)} FIT file(s), {len(nights)} night(s) of sleep and "
                      f"{len(hearts)} daily heart rate figure(s), {len(events)} batch(es)", events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    days = float(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    since = time.time() - days * 86400
    return run_over(config, fit_files(config, since=since),
                    datetime.fromtimestamp(since, timezone.utc).date() - timedelta(days=1), snapshot=False)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    # Every monitoring file and every night GarminDB holds is everything, so poll's
    # run is a snapshot, unless a file would not decode.
    return run_over(config, fit_files(config), None, snapshot=True)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    files = fit_files(config)
    found, logs = alerts(files)
    nights = sleeps(config)
    hearts = heart_rates(config)
    check(definitions, [envelope(definitions[ALERT_TYPE], p) for p in found]
          + [envelope(definitions[SLEEP_TYPE], p) for p in nights]
          + [envelope(definitions[HEART_TYPE], p) for p in hearts])
    if logs:
        return ductile.error(f"{len(logs)} of {len(files)} FIT file(s) would not decode", retry=False, logs=logs)
    versions = ", ".join(f"{t} v{definitions[t].version}" for t in (ALERT_TYPE, SLEEP_TYPE, HEART_TYPE))
    return ductile.ok(f"{len(found)} alert(s) in {len(files)} FIT file(s), {len(nights)} night(s) of sleep and "
                      f"{len(hearts)} daily heart rate figure(s), every one conforming to {versions}")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
