#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18", "garmin-fit-sdk==21.218.0"]
# ///
"""anam_garmin: shapes what a Garmin watch recorded into Anam envelopes, one batch
event at a time.

Six types. The abnormal high heart rate alert (health.heart-rate-alert), read
straight from the watch's monitoring FIT files under GarminDB's FitFiles/Monitoring:
GarminDB downloads those files but drops their event messages on import, so nothing
else holds the alert. This is the health ETL's fit_events.py (ductile-healthdata),
moved: the same event decoded the same way, and the same payload the health-db
worker built from the ETL's events table. From GarminDB's garmin.db: each night's
sleep (health.sleep-episode, the IEEE 1752 body with Garmin's score and averages beside
it), each day's resting, minimum and maximum heart rate (health.heart-rate-day,
Open mHealth), steps (activity.steps, Open mHealth) and the rest of the day as
Garmin wrote it (activity.day.garmin). From the activity FIT files under GarminDB's
FitFiles/Activities, each session the watch recorded (activity.exercise-session.garmin, the IEEE
1752 body with Garmin's measures beside it): the FIT file holds the start as a true
UTC instant, where garmin_activities.db holds it as wall clock, not always the same
one. Days and nights are timed by the Garmin Connect JSON GarminDB keeps beside
garmin.db, and every payload says in source_time how its time was read (anam card
197). It keeps no state of its own: Anam makes a resend a no-op.

Commands:
- handle : after a GarminDB sync, what changed in the last lookback_days
- poll   : everything, in batches: the resend-everything mode
- health : the sources are readable and everything in them conforms
"""

from __future__ import annotations

import json
import math
import sqlite3
import sys
import time
from datetime import date, datetime, timedelta, timezone
from datetime import time as clock
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import clock as clk  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

ALERT_TYPE = "health.heart-rate-alert"
SLEEP_TYPE = "health.sleep-episode"
HEART_TYPE = "health.heart-rate-day"
STEPS_TYPE = "activity.steps"
DAY_TYPE = "activity.day.garmin"
SESSION_TYPE = "activity.exercise-session.garmin"

# DAY_COLUMNS are daily_summary's columns activity.day.garmin keeps under the same name.
# Steps and the heart rate columns are other types; the TIME columns are kept in
# minutes (DAY_MINUTES); distance is renamed for its unit. These and DAY_GOALS are
# not configurable: they are GarminDB's schema and the Definition's fields.
DAY_COLUMNS = ("step_goal", "floors_up", "floors_down", "floors_goal", "calories_goal", "calories_total",
               "calories_bmr", "calories_active", "calories_consumed", "hydration_goal", "hydration_intake",
               "sweat_loss", "stress_avg", "spo2_avg", "spo2_min", "rr_waking_avg", "rr_max", "rr_min",
               "bb_charged", "bb_max", "bb_min", "description")
DAY_MINUTES = {"moderate_activity_time": "moderate_activity_minutes",
               "vigorous_activity_time": "vigorous_activity_minutes",
               "intensity_time_goal": "intensity_time_goal_minutes"}
# DAY_GOALS are what Garmin writes on a day the watch recorded nothing.
DAY_GOALS = {"step_goal", "floors_goal", "calories_goal", "hydration_goal", "intensity_time_goal_minutes"}

# ZONE is the zone activity.day.garmin's Definition names, Australia/Sydney. Garmin's
# days follow the watch, so it is used only for a day Garmin gave no interval for,
# which is read as midnight to midnight there, and such a day says so (basis
# "assumption", anam card 197). Read from the Definition so it is stated once.
ZONE = json.loads((HERE / "definitions" / f"{DAY_TYPE}.json").read_text())["meta"]["time_semantics"]["fact_time"]["zone"]
BATCH_EVENT = "anam_garmin.batch"

# HR_HIGH_ALERT is the FIT event number the watch writes for an abnormal high
# heart rate alert. Garmin does not document it; it was read from a watch's files.
# Not configurable: it is what the watch writes.
HR_HIGH_ALERT = 66

# DEFAULT_LOOKBACK_DAYS bounds handle to the files a sync can have touched, unless
# config's lookback_days says otherwise. A monitoring file covers one day and the
# watch syncs at least daily.
DEFAULT_LOOKBACK_DAYS = 3

# DEFAULT_BUSY_MS is how long a read of garmin.db waits for GarminDB to finish a
# write before it gives up and asks to be retried, unless config's busy_timeout_ms
# says otherwise.
DEFAULT_BUSY_MS = 30_000


class Settings(NamedTuple):
    """This run's config, read and checked once, at the start of a command."""

    lookback_days: float
    busy_ms: int


def settings(config: Dict[str, Any]) -> Settings:
    return Settings(
        lookback_days=cfg.number(config, "lookback_days", DEFAULT_LOOKBACK_DAYS, 0, 3650, low_open=True),
        busy_ms=cfg.integer(config, "busy_timeout_ms", DEFAULT_BUSY_MS, 0, 600_000),
    )


def number(v: float) -> Any:
    """v as JSON writes a whole number: 117, not 117.0."""
    return int(v) if float(v).is_integer() else v


def alert(mesg: Dict[str, Any]) -> Dict[str, Any]:
    """One alert, as the health-db worker built it from the ETL's events row. The
    event's 16-bit data packs the heart rate that tripped the alert in the high byte
    and the threshold configured on the watch in the low byte."""
    data = int(mesg["data"])
    at = clk.utc_text(mesg["timestamp"])
    return {
        "source": "garmin",
        "kind": "hr_high_alert",
        "fact_time": at,
        "heart_rate": number(data >> 8),
        "threshold": number(data & 0xFF),
        "unit": "bpm",
        # A FIT timestamp is UTC by the format's definition.
        "source_time": clk.source_time(at, "UTC", "source"),
    }


def alerts_in(path: Path) -> List[Dict[str, Any]]:
    """The alerts in one monitoring FIT file."""
    return [alert(m) for m in decode(path).get("event_mesgs", [])
            if m.get("event") == HR_HIGH_ALERT and m.get("timestamp") is not None and m.get("data") is not None]


def fit_files(config: Dict[str, Any], key: str, since: Optional[float] = None) -> List[Path]:
    """The FIT files under the directory config[key] names, oldest name first; with
    since, only those modified at or after it."""
    root = Path(str(config[key]))
    if not root.is_dir():
        raise ductile.Failure(f"no {key} at {root}", retry=False)
    files = sorted(p for p in root.rglob("*.fit") if p.is_file())
    return files if since is None else modified_since(files, since)


def modified_since(files: List[Path], since: float) -> List[Path]:
    """files modified at or after since."""
    try:
        return [p for p in files if p.stat().st_mtime >= since]
    except FileNotFoundError as exc:
        raise vanished(exc) from exc


def vanished(exc: FileNotFoundError) -> ductile.Failure:
    """A file listed and then gone, as a GarminDB sync rewrites its folder. The next
    run lists it again or not at all, so it is worth retrying; skipping it instead
    would let a snapshot report its alerts absent."""
    return ductile.Failure(f"{exc.filename} went while the run read it", retry=True)


def alerts(files: List[Path]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every alert in files, once each, ordered by fact_time, and a log line per
    file that would not decode. The same alert in two files is one alert: the first
    file by name keeps it, as the ETL's INSERT OR IGNORE did."""
    return each_once(files, alerts_in, "fact_time")


def each_once(files: List[Path], read, key: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """What read finds in each of files, once per key, ordered by it, and a log line
    per file that would not decode. The first file by name keeps a repeated key."""
    seen: Dict[str, Dict[str, Any]] = {}
    logs: List[str] = []
    for path in files:
        try:
            found = read(path)
        except FileNotFoundError as exc:
            raise vanished(exc) from exc
        except ValueError as exc:
            logs.append(f"skipped {path.name}: {exc}")
            continue
        for item in found:
            seen.setdefault(item[key], item)
    return [seen[k] for k in sorted(seen)], logs


def decode(path: Path) -> Dict[str, List[Dict[str, Any]]]:
    """path's FIT messages. A file the SDK cannot decode is a ValueError."""
    try:
        from garmin_fit_sdk import Decoder, Stream
    except ImportError as exc:
        raise ductile.Failure(f"the garmin-fit-sdk package is not installed: {exc}", retry=False) from exc
    try:
        msgs, errors = Decoder(Stream.from_file(str(path))).read(convert_types_to_strings=True)
    except OSError as exc:
        if isinstance(exc, FileNotFoundError):
            raise
        raise ductile.Failure(f"FIT file {path}: {exc}", retry=True) from exc
    if errors:
        raise ValueError("; ".join(str(e) for e in errors))
    return msgs


# ACTIVITY_NAMES maps a FIT session's (sport, sub_sport) to the Definition's
# activity name, Google Fit's vocabulary; (sport, None) stands for any sub-sport.
# Cardio training has no Google Fit name. A pair not here is "unknown", and the
# payload's fit_sport and fit_sub_sport keep what the watch wrote either way. Not
# configurable: it is what the payload means, and a change supersedes every session.
ACTIVITY_NAMES = {
    ("walking", None): "walking",
    ("running", "treadmill"): "running.treadmill",
    ("running", None): "running",
    ("rowing", "indoor_rowing"): "rowing.machine",
    ("rowing", None): "rowing",
    ("training", "cardio_training"): "other",
}


def activity_name(sport: Optional[str], sub_sport: Optional[str]) -> str:
    return ACTIVITY_NAMES.get((sport, sub_sport)) or ACTIVITY_NAMES.get((sport, None)) or "unknown"


def fit_name(v: Any) -> Optional[str]:
    """A FIT enum as the SDK names it, or its number when the SDK has no name."""
    if isinstance(v, str) and v:
        return v
    if isinstance(v, int):
        return str(v)
    return None


def measure(v: Any) -> Any:
    """A FIT figure as a JSON number, or None when the watch wrote none: the SDK
    reads an invalid float as NaN."""
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return None
    return number(v)


# SESSION_MEASURES are the session message's figures a payload keeps as plain
# numbers, by the Definition's name for them.
SESSION_MEASURES = {"avg_hr_bpm": "avg_heart_rate", "max_hr_bpm": "max_heart_rate",
                    "avg_power_w": "avg_power", "max_power_w": "max_power", "descent_m": "total_descent",
                    "training_effect_aerobic": "total_training_effect",
                    "training_effect_anaerobic": "total_anaerobic_training_effect",
                    "training_load": "training_load_peak"}
# SESSION_UNITS are the figures a payload keeps as IEEE unit values.
SESSION_UNITS = {"duration": ("total_timer_time", "sec"), "kcal_burned": ("total_calories", "kcal"),
                 "base_movement_quantity": ("total_strokes", "strokes"),
                 "cumulative_elevation_gain": ("total_ascent", "m")}


def session(mesg: Dict[str, Any]) -> Dict[str, Any]:
    """One FIT session message as an activity.exercise-session.garmin payload. A figure the watch
    did not write is left out, and so is a zero distance, which is what the watch
    writes for a session that measures none."""
    start = clk.utc_text(mesg["start_time"])
    sport, sub_sport = fit_name(mesg.get("sport")), fit_name(mesg.get("sub_sport"))
    p: Dict[str, Any] = {
        "id": f"garmin:session:{start}",
        "activity_name": activity_name(sport, sub_sport),
        "effective_time_frame": {"time_interval": {
            "start_date_time": start, "duration": {"value": measure(mesg["total_elapsed_time"]), "unit": "sec"}}},
        "source": "Garmin",
        "source_time": clk.source_time(start, "UTC", "source"),
    }
    for key, v in (("fit_sport", sport), ("fit_sub_sport", sub_sport), ("sport_profile", mesg.get("sport_profile_name"))):
        if v:
            p[key] = v
    for key, (field, unit) in SESSION_UNITS.items():
        if measure(mesg.get(field)) is not None:
            p[key] = {"value": measure(mesg[field]), "unit": unit}
    if measure(mesg.get("total_distance")):
        p["distance"] = {"value": measure(mesg["total_distance"]), "unit": "m"}
    p.update({key: measure(mesg.get(field)) for key, field in SESSION_MEASURES.items()
              if measure(mesg.get(field)) is not None})
    return p


def sessions_in(path: Path) -> List[Dict[str, Any]]:
    """The sessions in one activity FIT file: most hold one, a multisport activity
    one per sport. A session with no start or length is not one."""
    return [session(m) for m in decode(path).get("session_mesgs", [])
            if m.get("start_time") is not None and measure(m.get("total_elapsed_time")) is not None]


def sessions(files: List[Path]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every session in files, once each, by id."""
    return each_once(files, sessions_in, "id")


def minutes(t: str) -> Any:
    """GarminDB's TIME text, "05:49:00.000000", as minutes: 349."""
    h, m, sec = t.split(":")
    return number(int(h) * 60 + int(m) + float(sec) / 60)


# GarminDB keeps what Garmin Connect sent, each day's summary and each night's sleep,
# as JSON beside the tables it builds from them. The JSON holds what the tables drop:
# every time in GMT beside the watch's own clock, so the offset the watch was at comes
# from Garmin, not from the zone GarminDB runs in (anam card 197). A day is the
# interval Garmin counted, which follows the watch across a flight.

# MAX_OFFSET is the widest offset from UTC any zone keeps (+14:00). A difference
# between Garmin's two clocks outside it, or not whole minutes, is no zone's offset.
# Not configurable: it is the world's, not ours.
MAX_OFFSET = timedelta(hours=14)


class Frame(NamedTuple):
    """When a payload was true: its effective_time_frame and its source_time."""

    frame: Dict[str, Any]
    source_time: Dict[str, Any]


def read_json(path: Path) -> Optional[Dict[str, Any]]:
    """path's JSON object, or None when GarminDB wrote no such file. A file that is
    not a JSON object is a ValueError."""
    try:
        body = json.loads(path.read_text())
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise ductile.Failure(f"{path}: {exc}", retry=True) from exc
    if not isinstance(body, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return body


def checked_offset(local_minus_gmt: timedelta, what: str) -> timedelta:
    """The watch's offset from UTC, as the difference between its two clocks."""
    if abs(local_minus_gmt) > MAX_OFFSET or local_minus_gmt % timedelta(minutes=1):
        raise ValueError(f"{what}: its local and GMT clocks differ by {local_minus_gmt}, which is no zone's offset")
    return local_minus_gmt


def wellness_clock(text: Any) -> datetime:
    """A wellness time as Garmin writes it, "2026-10-16T13:00:00.0", naive. The
    fraction is dropped: Garmin writes whole minutes, and Python 3.10 reads only
    three or six fraction digits."""
    return datetime.fromisoformat(str(text).split(".")[0])


WELLNESS = ("wellnessStartTimeGmt", "wellnessStartTimeLocal", "wellnessEndTimeGmt", "wellnessEndTimeLocal")


def summary_frame(fit_dir: Path, day: str, steps: Optional[int] = None) -> Optional[Frame]:
    """The interval Garmin counted for day, from its daily summary
    (<fit_dir>/<year>/daily_summary_<day>.json), or None when it gave none. Each
    end is written at its own offset: across a flight they differ. A day still in
    progress ends where Garmin had counted to; the next sync supersedes it. With
    steps, garmin.db's count for the day, a summary that counted otherwise is a
    ValueError: the interval would not be the one the totals were counted over."""
    name = f"daily_summary_{day}.json"
    s = read_json(fit_dir / day[:4] / name)
    if not s or not all(s.get(k) for k in WELLNESS):
        return None
    try:
        start_gmt, start_local, end_gmt, end_local = (wellness_clock(s[k]) for k in WELLNESS)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from exc
    start_off = checked_offset(start_local - start_gmt, name)
    end_off = checked_offset(end_local - end_gmt, name)
    if s.get("calendarDate") != day or start_local.date().isoformat() != day or end_gmt <= start_gmt:
        raise ValueError(f"{name}: its interval, {start_local} to {end_local}, is not day {day}'s")
    if steps is not None and s.get("totalSteps") is not None and s["totalSteps"] != steps:
        raise ValueError(f"{name} counts {s['totalSteps']} steps and garmin.db {steps}: GarminDB has not imported it yet")
    start, end = start_gmt.replace(tzinfo=timezone.utc), end_gmt.replace(tzinfo=timezone.utc)
    return Frame({"time_interval": {"start_date_time": clk.at_offset(start, start_off),
                                    "end_date_time": clk.at_offset(end, end_off)}},
                 clk.source_time(day, clk.offset_text(start_off), "source"))


def assumed_frame(day: str) -> Frame:
    """day as local midnight to the next in ZONE, for a day Garmin gave no interval
    for; its source_time says the zone was assumed. A midnight that does not exist
    once in ZONE is a ClockError."""
    d = date.fromisoformat(day)
    start = clk.local_instant(datetime.combine(d, clock(0)), ZONE)
    end = clk.local_instant(datetime.combine(d + timedelta(days=1), clock(0)), ZONE)
    return Frame({"time_interval": {"start_date_time": clk.at_offset(start, start.utcoffset()),
                                    "end_date_time": clk.at_offset(end, end.utcoffset())}},
                 clk.source_time(day, ZONE, "assumption"))


class Read(NamedTuple):
    """What a read of one kind of record found: each record's Frame by its key, a
    log line for each record assumed or left out, and whether any was left out."""

    frames: Dict[str, Frame]
    logs: List[str]
    lost: bool


def day_frames(fit_dir: Path, days: List[str], steps: Dict[str, int]) -> Read:
    """Each of days' Frame: Garmin's where it gave one, else assumed. A day whose
    summary contradicts itself, or whose assumed midnight is not one instant, is left
    out, since no interval could be said for it without a guess."""
    frames: Dict[str, Frame] = {}
    logs: List[str] = []
    lost = False
    for day in sorted(set(days)):
        try:
            f = summary_frame(fit_dir, day, steps.get(day))
            if f is None:
                f = assumed_frame(day)
                logs.append(f"day {day}: Garmin gave no interval, so it is taken as midnight to midnight in {ZONE} "
                            "(basis assumption)")
        except ValueError as exc:
            logs.append(f"skipped day {day}: {exc}")
            lost = True
            continue
        frames[day] = f
    return Read(frames, logs, lost)


SLEEP_CLOCKS = ("sleepStartTimestampGMT", "sleepStartTimestampLocal", "sleepEndTimestampGMT", "sleepEndTimestampLocal")


def sleep_frame(sleep_dir: Path, day: str) -> Frame:
    """A night's start and end as Garmin's GMT epochs, written on the watch's clock,
    from GarminDB's copy of Garmin's sleep (<sleep_dir>/sleep_<day>.json). Its
    source_time keeps the start's epoch as Garmin wrote it, which is UTC; the watch's
    offset is in the frame. A night the file does not time is a ValueError."""
    name = f"sleep_{day}.json"
    dto = (read_json(sleep_dir / name) or {}).get("dailySleepDTO") or {}
    if dto.get("calendarDate") != day or not all(type(dto.get(k)) is int for k in SLEEP_CLOCKS):
        raise ValueError(f"{name} holds no GMT and local start and end for the night")
    start_ms, start_local_ms, end_ms, end_local_ms = (dto[k] for k in SLEEP_CLOCKS)
    start_off = checked_offset(timedelta(milliseconds=start_local_ms - start_ms), name)
    end_off = checked_offset(timedelta(milliseconds=end_local_ms - end_ms), name)
    start = datetime.fromtimestamp(start_ms / 1000, timezone.utc)
    end = datetime.fromtimestamp(end_ms / 1000, timezone.utc)
    if end <= start:
        raise ValueError(f"{name}: the night ends before it starts")
    return Frame({"time_interval": {"start_date_time": clk.at_offset(start, start_off),
                                    "end_date_time": clk.at_offset(end, end_off)}},
                 clk.source_time(str(start_ms), "UTC", "source"))


def sleep_episode(row: sqlite3.Row, f: Frame) -> Dict[str, Any]:
    """One night of Garmin's sleep table as a health.sleep-episode payload, timed by
    Garmin's sleep JSON."""
    p: Dict[str, Any] = {
        "id": f"sleep:{row['day']}",
        "effective_time_frame": f.frame,
        "total_sleep_time": {"value": minutes(row["total_sleep"]), "unit": "min"},
        "light_sleep_duration": {"value": minutes(row["light_sleep"]), "unit": "min"},
        "deep_sleep_duration": {"value": minutes(row["deep_sleep"]), "unit": "min"},
        "rem_sleep_duration": {"value": minutes(row["rem_sleep"]), "unit": "min"},
        "wake_after_sleep_onset": {"value": minutes(row["awake"]), "unit": "min"},
        # Garmin's sleep table holds one sleep a day, its main one; the importer
        # says so, Garmin does not, and the Definition's description records that.
        "is_main_sleep": True,
        "source_time": f.source_time,
    }
    for key in ("score", "qualifier"):
        if row[key] not in (None, ""):
            p[key] = row[key]
    for key in ("avg_spo2", "avg_rr", "avg_stress"):
        if row[key] is not None:
            p[key] = number(row[key])
    return p


def sleeps(config: Dict[str, Any], busy_ms: int, since: Optional[date] = None) -> Tuple[List[Dict[str, Any]], Read]:
    """Every night garmin.db's sleep table holds, by day; with since, those from that
    day on. A day without a start is a day the watch saw no sleep: no episode. A night
    Garmin's sleep JSON does not time is left out."""
    rows = query(config, busy_ms, 'SELECT day, start, "end", total_sleep, deep_sleep, light_sleep, rem_sleep, awake, '
                         "avg_spo2, avg_rr, avg_stress, score, qualifier FROM sleep "
                         'WHERE start IS NOT NULL AND "end" IS NOT NULL AND day >= ? ORDER BY day', since)
    sleep_dir = folder(config, "sleep_dir")
    nights: List[Dict[str, Any]] = []
    frames: Dict[str, Frame] = {}
    logs: List[str] = []
    for r in rows:
        try:
            frames[r["day"]] = sleep_frame(sleep_dir, r["day"])
        except ValueError as exc:
            logs.append(f"skipped night {r['day']}: {exc}")
            continue
        nights.append(sleep_episode(r, frames[r["day"]]))
    return nights, Read(frames, logs, len(frames) < len(rows))


def folder(config: Dict[str, Any], key: str) -> Path:
    """The directory config[key] names."""
    root = Path(str(config[key]))
    if not root.is_dir():
        raise ductile.Failure(f"no {key} at {root}", retry=False)
    return root


def query(config: Dict[str, Any], busy_ms: int, sql: str, since: Optional[date]) -> List[sqlite3.Row]:
    """sql's rows from garmin_db, opened read-only, waiting up to busy_ms for a
    write; its one parameter is the first day wanted."""
    path = Path(str(config["garmin_db"]))
    if not path.is_file():
        raise ductile.Failure(f"no garmin_db at {path}", retry=False)
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=busy_ms / 1000)
        conn.row_factory = sqlite3.Row
        try:
            return conn.execute(sql, ((since or date.min).isoformat(),)).fetchall()
        finally:
            conn.close()
    except sqlite3.OperationalError as exc:
        raise ductile.Failure(f"garmin_db {path}: {exc}", retry=True) from exc


def heart_figure(day: str, statistic: str, bpm: float, f: Frame) -> Dict[str, Any]:
    p: Dict[str, Any] = {"id": day, "statistic": statistic,
                         "heart_rate": {"value": number(bpm), "unit": "beats/min"},
                         "effective_time_frame": f.frame, "source_time": f.source_time}
    if statistic == "resting":
        p["temporal_relationship_to_physical_activity"] = "at rest"
    else:
        p["descriptive_statistic"] = statistic
    return p


class Days(NamedTuple):
    """The day-keyed types, each day timed by Garmin's interval for it."""

    steps: List[Dict[str, Any]]
    records: List[Dict[str, Any]]
    heart: List[Dict[str, Any]]
    read: Read


def days(config: Dict[str, Any], busy_ms: int, since: Optional[date] = None) -> Days:
    """Each day of daily_summary as an activity.steps and an activity.day.garmin, and each
    day's resting heart rate (resting_hr) and its minimum and maximum
    (daily_summary) as health.heart-rate-day figures. A day holding only goals and
    zero times is a day the watch recorded nothing: no steps and no record. A figure
    Garmin left empty is no facet."""
    cols = ", ".join(("day", "steps", "distance", "hr_min", "hr_max") + DAY_COLUMNS + tuple(DAY_MINUTES))
    daily = query(config, busy_ms, f"SELECT {cols} FROM daily_summary WHERE day >= ? ORDER BY day", since)
    resting = query(config, busy_ms, "SELECT day, resting_heart_rate FROM resting_hr "
                                     "WHERE resting_heart_rate IS NOT NULL AND day >= ?", since)
    read = day_frames(folder(config, "fit_dir"), [r["day"] for r in daily] + [r["day"] for r in resting],
                      {r["day"]: int(r["steps"]) for r in daily if r["steps"] is not None})
    timed = read.frames
    out = Days([], [], [], read)
    for r in daily:
        f = timed.get(r["day"])
        if f is None:
            continue
        if r["steps"] is not None:
            out.steps.append({"id": f"steps:{r['day']}", "step_count": {"value": int(r["steps"]), "unit": "steps"},
                              "effective_time_frame": f.frame, "source_time": f.source_time})
        rec: Dict[str, Any] = {k: number(r[k]) if isinstance(r[k], float) else r[k]
                               for k in DAY_COLUMNS if r[k] not in (None, "")}
        if r["distance"] is not None:
            rec["distance_km"] = number(r["distance"])
        rec.update({name: minutes(r[col]) for col, name in DAY_MINUTES.items() if r[col]})
        measured = {k for k, v in rec.items() if k not in DAY_GOALS and v != 0}
        if measured or r["steps"] is not None:
            out.records.append({"id": f"day:{r['day']}", "day": r["day"], **rec,
                                "effective_time_frame": f.frame, "source_time": f.source_time})
    figures = [heart_figure(r["day"], "resting", r["resting_heart_rate"], timed[r["day"]])
               for r in resting if r["day"] in timed]
    for r in daily:
        figures += [heart_figure(r["day"], stat, r[col], timed[r["day"]])
                    for stat, col in (("minimum", "hr_min"), ("maximum", "hr_max"))
                    if r[col] is not None and r["day"] in timed]
    order = {"resting": 0, "minimum": 1, "maximum": 2}
    out.heart.extend(sorted(figures, key=lambda f: (f["id"], order[f["statistic"]])))
    return out


# Ids name what they are ("sleep:", "steps:", "day:") because a facet's id is the
# source plus its identity values, without the type: two of this importer's types
# keyed on a bare date would be one facet (anam card 55).


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
        payload: Dict[str, Any] = {"envelopes": g, "definitions": definitions.manifests([definition.type]),
                                   "batch": label}
        if part is not None:
            payload["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, payload))
    return events


class Shaped(NamedTuple):
    """One run's payloads by type, its log lines, and whether it left anything out:
    a FIT file that would not decode, or a day or night Garmin did not time."""

    by_type: Dict[str, List[Dict[str, Any]]]
    logs: List[str]
    complete: bool


def shape(config: Dict[str, Any], busy_ms: int, monitoring: List[Path], activities: List[Path],
          since: Optional[date]) -> Shaped:
    """Every type's payloads from the given FIT files and garmin.db from since on."""
    found, alert_logs = alerts(monitoring)
    held, session_logs = sessions(activities)
    nights, slept = sleeps(config, busy_ms, since)
    d = days(config, busy_ms, since)
    return Shaped({ALERT_TYPE: found, SLEEP_TYPE: nights, HEART_TYPE: d.heart, STEPS_TYPE: d.steps,
                   DAY_TYPE: d.records, SESSION_TYPE: held},
                  alert_logs + session_logs + slept.logs + d.read.logs,
                  not (alert_logs or session_logs or slept.lost or d.read.lost))


def run_over(config: Dict[str, Any], s: Settings, monitoring: List[Path], activities: List[Path],
             since: Optional[date], snapshot: bool) -> Dict[str, Any]:
    shaped = shape(config, s.busy_ms, monitoring, activities, since)
    # A run that left something out is not everything, so it is no snapshot.
    events = batch_events(load(HERE), shaped.by_type, str(config["person_id"]), snapshot and shaped.complete)
    n = {t: len(ps) for t, ps in shaped.by_type.items()}
    return ductile.ok(f"{n[ALERT_TYPE]} alert(s) in {len(monitoring)} monitoring FIT file(s), {n[SESSION_TYPE]} "
                      f"session(s) in {len(activities)} activity FIT file(s), {n[SLEEP_TYPE]} night(s) of sleep, "
                      f"{n[HEART_TYPE]} daily heart rate figure(s), {n[STEPS_TYPE]} day(s) of steps and "
                      f"{n[DAY_TYPE]} day record(s), {len(events)} batch(es)", events=events, logs=shaped.logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    since = time.time() - s.lookback_days * 86400
    # garmin.db is read from the day before the cutoff's UTC day, so the local day
    # holding the cutoff is read whole in any zone.
    return run_over(config, s, fit_files(config, "fit_dir", since), fit_files(config, "activities_dir", since),
                    datetime.fromtimestamp(since, timezone.utc).date() - timedelta(days=1), snapshot=False)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    # Every FIT file and every day and night GarminDB holds is everything, so poll's
    # run is a snapshot, unless it left something out.
    return run_over(config, s, fit_files(config, "fit_dir"), fit_files(config, "activities_dir"), None, snapshot=True)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    definitions = load(HERE)
    monitoring, activities = fit_files(config, "fit_dir"), fit_files(config, "activities_dir")
    files = monitoring + activities
    shaped = shape(config, s.busy_ms, monitoring, activities, None)
    check(definitions, [envelope(definitions[t], p) for t, ps in shaped.by_type.items() for p in ps])
    if not shaped.complete:
        return ductile.error("a FIT file would not decode, or Garmin did not time a day or night", retry=False,
                             logs=shaped.logs)
    counts = ", ".join(f"{len(ps)} {t} v{definitions[t].version}" for t, ps in shaped.by_type.items())
    return ductile.ok(f"{counts} from {len(files)} FIT file(s), every one conforming", logs=shaped.logs)


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
