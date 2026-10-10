#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["garmin-fit-sdk==21.218.0"]
# ///
"""Writes a FIT file for the tests: argv[1] is the path. Stdin is a JSON list of
[iso timestamp, event number, data] for a monitoring file, or {"sessions": [...]}
for an activity file, each session its message's fields with start_time as ISO.
Run under uv, so the tests need no FIT SDK of their own."""

import json
import sys
from datetime import datetime
from pathlib import Path

from garmin_fit_sdk import Encoder, Profile

MESG = Profile["mesg_num"]


def main() -> None:
    path = Path(sys.argv[1])
    given = json.load(sys.stdin)
    enc = Encoder()
    enc.write_mesg({"mesg_num": MESG["FILE_ID"], "type": "activity" if isinstance(given, dict) else "monitoring_b",
                    "manufacturer": "garmin", "time_created": datetime.fromisoformat("2026-09-25T00:00:00+00:00")})
    if isinstance(given, dict):
        for fields in given["sessions"]:
            start = datetime.fromisoformat(fields.pop("start_time"))
            enc.write_mesg({"mesg_num": MESG["SESSION"], "start_time": start, "timestamp": start, **fields})
    else:
        for ts, event, data in given:
            enc.write_mesg({"mesg_num": MESG["EVENT"], "timestamp": datetime.fromisoformat(ts),
                            "event": event, "event_type": "marker", "data": data})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(enc.close())


if __name__ == "__main__":
    main()
