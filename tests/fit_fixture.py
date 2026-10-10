#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["garmin-fit-sdk==21.218.0"]
# ///
"""Writes a monitoring FIT file for the tests: argv[1] is the path, stdin a JSON
list of [iso timestamp, event number, data]. Run under uv, so the tests need no
FIT SDK of their own."""

import json
import sys
from datetime import datetime
from pathlib import Path

from garmin_fit_sdk import Encoder, Profile

MESG = Profile["mesg_num"]


def main() -> None:
    path = Path(sys.argv[1])
    enc = Encoder()
    enc.write_mesg({"mesg_num": MESG["FILE_ID"], "type": "monitoring_b", "manufacturer": "garmin",
                    "time_created": datetime.fromisoformat("2026-09-25T00:00:00+00:00")})
    for ts, event, data in json.load(sys.stdin):
        enc.write_mesg({"mesg_num": MESG["EVENT"], "timestamp": datetime.fromisoformat(ts),
                        "event": event, "event_type": "marker", "data": data})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(enc.close())


if __name__ == "__main__":
    main()
