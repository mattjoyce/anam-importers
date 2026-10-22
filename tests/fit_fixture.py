#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["garmin-fit-sdk==21.218.0"]
# ///
"""Writes a FIT file for the tests: argv[1] is the path. Stdin is {"sessions": [...]}
for an activity file, each session its message's fields with start_time as ISO;
{"events": [[iso timestamp, event number, data], ...], "monitoring": [{...}, ...]} for
a monitoring file, each monitoring message its fields with timestamp as ISO; or a bare
list of events, which is a monitoring file of alerts alone. Run under uv, so the tests
need no FIT SDK of their own."""

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from garmin_fit_sdk import Encoder, Profile

MESG = Profile["mesg_num"]


def fields(given: Dict[str, Any]) -> Dict[str, Any]:
    """One monitoring message's fields, with an ISO timestamp read as the datetime the
    encoder writes."""
    out = dict(given)
    if isinstance(out.get("timestamp"), str):
        out["timestamp"] = datetime.fromisoformat(out["timestamp"])
    return out


def main() -> None:
    path = Path(sys.argv[1])
    given = json.load(sys.stdin)
    sessions = given["sessions"] if isinstance(given, dict) and "sessions" in given else None
    events = given.get("events", []) if isinstance(given, dict) else given
    monitoring = given.get("monitoring", []) if isinstance(given, dict) else []
    enc = Encoder()
    enc.write_mesg({"mesg_num": MESG["FILE_ID"], "type": "activity" if sessions is not None else "monitoring_b",
                    "manufacturer": "garmin", "time_created": datetime.fromisoformat("2015-09-25T00:00:00+00:00")})
    for session in sessions or []:
        start = datetime.fromisoformat(session.pop("start_time"))
        enc.write_mesg({"mesg_num": MESG["SESSION"], "start_time": start, "timestamp": start, **session})
    for ts, event, data in events:
        enc.write_mesg({"mesg_num": MESG["EVENT"], "timestamp": datetime.fromisoformat(ts),
                        "event": event, "event_type": "marker", "data": data})
    for message in monitoring:
        enc.write_mesg({"mesg_num": MESG["MONITORING"], **fields(message)})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(enc.close())


if __name__ == "__main__":
    main()
