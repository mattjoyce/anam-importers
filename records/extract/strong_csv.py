#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Strong app CSV export -> a records file of activity.exercise-session.strong, one record per workout.

Usage: strong_csv.py --out-dir DIR --zone ZONE [--max-session-sec N] strong<digits>.csv

The export is one row per set, semicolon-separated. A workout is identified by its start
time (the "Workout #" column is renumbered per export, so it is not identity). Each record
carries the workout's rows verbatim under `sets`, in file order, minus the workout-level
columns; "Rest Timer" and "Note" rows stay as rows, because that is what the source says.
Deterministic; ids are strong:session:<ISO start>. (Version 1 wrote activity.gym-visit with ids
strong:<ISO start>; a new type takes new ids, so the move is by retraction, not supersession.)

Each payload conforms to IEEE 1752.1 physical-activity-1.0 as `strength_training`, which
requires an interval. Strong keeps a workout open until the next one starts, so its duration
is unreliable (some run for days, one is negative). The person's rule (2026-10-08): a Strong
session is 3 hours at most, the default of --max-session-sec. The interval's duration is
Strong's own figure when it is above 0 and at most the cap, and the cap otherwise; then
`duration_capped: true` marks it, and Strong's number is always kept as reported_duration_sec.
Another cap writes other records, and a resend of them supersedes. The start is Strong's local clock read in
ZONE; a workout logged elsewhere is placed as if in ZONE.

Moved from Anam's scripts/extract-strong-csv.py (anam card 58); the records are the same.
"""
import argparse
import csv
import hashlib
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

# MAX_SESSION_SEC is the longest a session is taken to be, unless --max-session-sec
# says otherwise.
MAX_SESSION_SEC = 3 * 3600
METHOD = "records/extract/strong_csv.py"


def num(s):
    if s in ("", None):
        return None
    f = float(s)
    return int(f) if f.is_integer() else f


def extract(p: Path, zone: str, max_session_sec: int = MAX_SESSION_SEC) -> tuple:
    """The records file's content, and how many CSV rows it was read from. A
    session's duration is capped at max_session_sec."""
    tz = ZoneInfo(zone)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    with open(p, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    workouts = OrderedDict()
    for r in rows:
        workouts.setdefault(r["Date"], []).append(r)
    records = []
    for start, wrows in workouts.items():
        first = wrows[0]
        iso = start.replace(" ", "T")
        at = datetime.fromisoformat(start).replace(tzinfo=tz)
        reported = num(first["Duration (sec)"])
        capped = not (0 < reported <= max_session_sec)
        rec = {"type": "activity.exercise-session.strong", "id": f"strong:session:{iso}",
               "activity_name": "strength_training",
               "effective_time_frame": {"time_interval": {
                   "start_date_time": at.isoformat(timespec="seconds"),
                   "duration": {"value": max_session_sec if capped else reported, "unit": "sec"}}},
               "source": "Strong", "workout_name": first["Workout Name"],
               "reported_duration_sec": reported}
        if capped:
            rec["duration_capped"] = True
        notes = sorted({r["Workout Notes"] for r in wrows if r["Workout Notes"]})
        if notes:
            rec["workout_notes"] = notes
        exercises = []
        for r in wrows:
            if r["Exercise Name"] not in exercises:
                exercises.append(r["Exercise Name"])
        rec["exercises"] = exercises
        sets = []
        for r in wrows:
            s = {"exercise": r["Exercise Name"], "set": r["Set Order"]}
            for col, key in (("Weight (kg)", "kg"), ("Reps", "reps"), ("RPE", "rpe"),
                             ("Distance (meters)", "distance_m"), ("Seconds", "seconds")):
                v = num(r[col])
                if v is not None:
                    s[key] = v
            if r["Notes"]:
                s["note"] = r["Notes"]
            sets.append(s)
        rec["sets"] = sets
        records.append(rec)
    return {"document": {"name": p.name, "sha256": sha}, "extracted": {"method": METHOD, "version": 2},
            "records": records}, len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zone", required=True, help="the IANA zone Strong's clock reads in")
    ap.add_argument("--max-session-sec", type=int, default=MAX_SESSION_SEC,
                    help=f"the longest a session is taken to be, in seconds (default {MAX_SESSION_SEC}, 3 hours)")
    ap.add_argument("csv")
    a = ap.parse_args()
    if not 60 <= a.max_session_sec <= 7 * 86400:
        ap.error(f"--max-session-sec {a.max_session_sec} is outside 60..{7 * 86400}")
    doc, n = extract(Path(a.csv), a.zone, a.max_session_sec)
    records = doc["records"]
    out = Path(a.out_dir) / f"strong-workouts.{doc['document']['sha256'][:12]}.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    print(f"{out.name}: {len(records)} workouts from {n} rows, {records[0]['id'][15:25]} to {records[-1]['id'][15:25]}")


if __name__ == "__main__":
    main()
