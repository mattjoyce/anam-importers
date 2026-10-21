#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Fitbit "Sleep Logs.xlsx" -> a records file of health.sleep-episode.

Usage: fitbit_sleep.py --out-dir DIR --zone ZONE "Sleep Logs.xlsx"

The workbook has no header row. It reads as an IFTTT "Fitbit sleep logged" applet writes
a spreadsheet: its "Month D, YYYY at HH:MMAM" dates, and its fields as text/seconds pairs
in the applet's order (bed time; time asleep; time to fall asleep; time awake; awake
count; restless count; restless time; wake time). C is seconds asleep and G seconds
awake, and on every row they add up to the time from A (start) to L (end), read on the
wall clock in ZONE, which is what proves the reading; a row where they do not stops the
run. H, I and K (seconds) are kept as awake_count, restless_count and restless_minutes,
under the applet's names. D/E, time to fall asleep, is always zero and left out.

Each record is the IEEE 1752 sleep-episode body of anam_garmin's health.sleep-episode: the
interval in UTC, total_sleep_time and wake_after_sleep_onset in minutes. is_main_sleep
is not written, since Fitbit does not say. source_time keeps A, the start as the workbook
wrote it, read in ZONE by the person's --zone (basis configuration, anam card 198). A
wall clock ZONE skips or repeats (daylight saving) stops the run, naming the row: it
names no one instant. Ids are fitbit:sleep:<local start>, distinct from Garmin's
sleep:<day>. Deterministic: the same workbook yields the same records.
"""
import argparse
import hashlib
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from anam_importer import clock  # noqa: E402
from xlsx import rows  # noqa: E402

METHOD = "records/extract/fitbit_sleep.py"
LAYOUT = "%B %d, %Y at %I:%M%p"


def minutes(seconds: str) -> object:
    m = float(seconds) / 60
    return int(m) if m.is_integer() else m


def wall(text: str, zone: str, n: int):
    """The workbook's wall clock text, read in zone; one zone skips or repeats stops
    the run."""
    try:
        return clock.local_instant(datetime.strptime(text, LAYOUT), zone)
    except clock.ClockError as exc:
        raise SystemExit(f"row {n}: {exc}") from exc


def extract(p: Path, zone: str) -> dict:
    clock.check_zone(zone)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    records, ids = [], set()
    with zipfile.ZipFile(p) as z:
        for n, c in enumerate(rows(z), start=1):
            start = wall(c["A"], zone, n)
            end = wall(c["L"], zone, n)
            asleep, awake = float(c["C"]), float(c["G"])
            if asleep + awake != (end - start).total_seconds():
                raise SystemExit(f"row {n} ({c['A']}): asleep {asleep}s and awake {awake}s do not fill "
                                 f"{c['A']} to {c['L']}; the columns may not be what this reads")
            rid = f"fitbit:sleep:{start:%Y-%m-%dT%H:%M}"
            if rid in ids:
                raise SystemExit(f"row {n}: a second sleep starting {c['A']}")
            ids.add(rid)
            records.append({
                "type": "health.sleep-episode", "id": rid,
                "effective_time_frame": {"time_interval": {
                    "start_date_time": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "end_date_time": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}},
                "total_sleep_time": {"value": minutes(c["C"]), "unit": "min"},
                "wake_after_sleep_onset": {"value": minutes(c["G"]), "unit": "min"},
                "awake_count": int(float(c["H"])),
                "restless_count": int(float(c["I"])),
                "restless_minutes": minutes(c["K"]),
                "source_time": clock.source_time(c["A"], zone, "configuration"),
            })
    return {"document": {"name": p.name, "sha256": sha}, "extracted": {"method": METHOD, "version": 3},
            "records": records}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--zone", required=True, help="the IANA zone the workbook's wall clock reads in")
    ap.add_argument("xlsx")
    a = ap.parse_args()
    doc = extract(Path(a.xlsx), a.zone)
    records = doc["records"]
    out = Path(a.out_dir) / f"fitbit-sleep-logs.{doc['document']['sha256'][:12]}.yaml"
    out.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100))
    print(f"{out.name}: {len(records)} sleeps, {records[0]['id'][13:]} to {records[-1]['id'][13:]}")


if __name__ == "__main__":
    main()
