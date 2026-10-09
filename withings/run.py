#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18"]
# ///
"""anam_withings: shapes the withings plugin's measurements into health.measurement
envelopes for Anam, one batch event at a time.

It reads the withings plugin's own database, read-only, and knows that one vendor's
tables; Anam knows none. One measurement is one envelope, its payload the source's
own lexemes with its group's attribution beside it, exactly as the built-in worker
Anam carried before (internal/capture/withings). The identity is (withings_id,
type), composed by Anam's gate from the Definition, so the same measurement from
either path is the same facet.

Commands:
- handle : on withings.measurement_recorded, the batch for that one measure group;
           on withings.reconciled, every measurement, since a reconcile can change
           old groups' attribution
- poll   : every measurement the database holds, in batches: the resend-everything
           mode, for a schedule, a rebuild or a manual run
- health : the database is readable and every row it holds conforms
"""

from __future__ import annotations

import math
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load  # noqa: E402
from anam_importer import ductile  # noqa: E402

TYPE = "health.measurement"
BATCH_EVENT = "anam_withings.batch"

# ATTRIB_AMBIGUOUS is Withings' attrib for a reading the device could not place: it
# "may belong to other users as well as this one". Such a reading asserts no one, so
# Anam binds it at medium rather than high. Every other attrib is the account's.
ATTRIB_AMBIGUOUS = "1"

# Every column but value is read through CAST(... AS TEXT), as the source wrote it.
# value is a REAL, and a REAL has no lexeme: SQLite's text for it depends on the
# SQLite build (3.43 changed it; the build in Anam's Go worker writes
# 29.371000000000002 where Python's writes 29.371). So value is read as the double
# it is and written as its shortest round-trip decimal (render), which IEEE 754
# fixes whatever reads it. The local surrogate id, the sync clock and the group's
# bookkeeping clocks are left out: none is a health fact, and each would supersede
# a facet for a re-sync that changed nothing.
QUERY = """
    SELECT CAST(m.withings_id AS TEXT), CAST(m.date AS TEXT), CAST(m.type AS TEXT),
           m.value, CAST(m.unit AS TEXT),
           CAST(g.attrib AS TEXT), g.model, g.deviceid, g.timezone
    FROM measurements m
    LEFT JOIN measure_groups g ON g.withings_id = m.withings_id
    {where}
    ORDER BY m.withings_id, m.type
"""

FIELDS = ("withings_id", "date", "type", "value", "unit", "attrib", "model", "deviceid", "timezone")


# DEFAULT_BUSY_MS is how long a read waits for the withings plugin to finish a write
# before it gives up and asks to be retried.
DEFAULT_BUSY_MS = 5000


def read_source(config: Dict[str, Any], withings_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """The payloads in the withings database, every one or one group's. A database
    that is busy is a failure worth retrying; one that is missing or the wrong shape
    is not, until someone changes it."""
    try:
        conn = open_source(str(config["db_path"]), int(config.get("busy_timeout_ms", DEFAULT_BUSY_MS)))
        try:
            return payloads(conn, withings_id)
        finally:
            conn.close()
    except sqlite3.Error as exc:
        busy = isinstance(exc, sqlite3.OperationalError) and ("locked" in str(exc) or "busy" in str(exc))
        raise ductile.Failure(f"withings database {config['db_path']}: {exc}", retry=busy) from exc


def open_source(db_path: str, busy_ms: int = DEFAULT_BUSY_MS) -> sqlite3.Connection:
    """The withings database, read-only. It must carry measure_groups (the withings
    plugin 0.4.0 after its reconcile), or attribution is unknown."""
    path = Path(db_path)
    if not path.is_file():
        raise ductile.Failure(f"no withings database at {db_path}", retry=False)
    conn = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=busy_ms / 1000)
    has = conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = 'measure_groups'").fetchone()[0]
    if not has:
        conn.close()
        raise ductile.Failure("the withings database has no measure_groups table, so attribution is unknown; "
                              "run the withings plugin's reconcile", retry=False)
    return conn


def payloads(conn: sqlite3.Connection, withings_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """One payload per measurement, every one or one group's, in a stable order. A
    column the source left NULL is left out, not written as null."""
    if withings_id is None:
        rows = conn.execute(QUERY.format(where=""))
    else:
        rows = conn.execute(QUERY.format(where="WHERE m.withings_id = ?"), (int(withings_id),))
    out = []
    for row in rows:
        p = {k: v for k, v in zip(FIELDS, row) if v is not None}
        if "value" in p:
            p["value"] = render(p["value"])
        out.append(p)
    return out


def render(value: float) -> str:
    """A measurement's value as the shortest decimal that reads back as the same
    double, written out in full with .0 on a whole number: 80.5, 29.371, 99.0,
    0.00001. Never an exponent: the Definition's value is a plain decimal."""
    v = float(value)
    if not math.isfinite(v):
        raise ValueError(f"value {value!r} is not a finite number")
    s = format(Decimal(repr(v)), "f")
    return s if "." in s else s + ".0"


def envelopes_of(definition: Definition, rows: List[Dict[str, Any]], person: str) -> List[Dict[str, Any]]:
    """An envelope per payload. An ambiguous group asserts no one."""
    return [
        envelope(definition, p, asserted_person=None if p.get("attrib") == ATTRIB_AMBIGUOUS else person)
        for p in rows
    ]


def batch_events(request: Dict[str, Any], withings_id: Optional[int]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    definition = definitions[TYPE]
    rows = read_source(config, withings_id)
    envs = envelopes_of(definition, rows, str(config["person_id"]))
    check(definitions, envs)

    groups = list(batches(envs))
    manifest = definition.body.decode()
    events = [
        ductile.event(BATCH_EVENT, {"envelopes": g, "definitions": [manifest], "batch": f"{i + 1}/{len(groups)}"})
        for i, g in enumerate(groups)
    ]
    what = "every measurement" if withings_id is None else f"group {withings_id}"
    return ductile.ok(f"{len(envs)} measurement(s) of {what} in {len(groups)} batch(es)", events=events)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    event = request.get("event") or {}
    if event.get("type") == "withings.reconciled":
        return batch_events(request, None)
    withings_id = ductile.payload_of(request).get("withings_id")
    if withings_id is None:
        return ductile.error("the event names no withings_id", retry=False)
    return batch_events(request, int(withings_id))


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    return batch_events(request, None)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    rows = read_source(config)
    check(definitions, envelopes_of(definitions[TYPE], rows, "health-check"))
    return ductile.ok(f"{len(rows)} measurement(s), every one conforming to {TYPE} v{definitions[TYPE].version}")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
