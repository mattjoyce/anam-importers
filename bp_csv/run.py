#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18"]
# ///
"""anam_bp_csv: shapes a blood pressure app export into health.blood-pressure
envelopes for Anam, one batch event at a time.

The export is a CSV the phone app writes as BloodPressure_<date>, messy in ways
this absorbs rather than corrects: fields padded with tabs and spaces, strings
carrying their own quotes, CRLF line ends, and several distinct readings sharing
one timestamp. It never touches a value: "137.0" reaches Anam as the export wrote
it, typos in comments included. This is Anam's built-in bpcsv worker
(internal/capture/bpcsv), moved, so the same row from either path is the same
facet: identity is (date_excel, reading), where reading is the row's ordinal
within its timestamp, composed by Anam's gate from the Definition.

Commands:
- handle : on a folder_watch per_file event, the export at its path; a deleted
           path is nothing to do
- poll   : every export under export_dir, in batches: the resend-everything mode,
           for a rebuild or a manual run
- health : export_dir is readable and every row of every export conforms
"""

from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402

TYPE = "health.blood-pressure"
BATCH_EVENT = "anam_bp_csv.batch"

# DEFAULT_PATTERN matches the app's export names. The name changes with every
# export, and nothing about identity is read from it.
DEFAULT_PATTERN = "BloodPressure_*"


def records(text: str) -> Iterator[List[str]]:
    """The export's records, split as Go's encoding/csv splits them with
    TrimLeadingSpace and LazyQuotes, which is how the built-in worker read it.

    Leading whitespace of a field is dropped, so a field the export pads before its
    opening quote is still a quoted field. Inside one, "" is a quote, and a quote not
    followed by a comma or the line's end is kept as it stands. A blank line is no
    record. CRLF is LF.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        if line == "":
            continue
        record: List[str] = []
        pos = 0
        while True:
            while pos < len(line) and line[pos].isspace():
                pos += 1
            if pos < len(line) and line[pos] == '"':
                pos += 1
                field: List[str] = []
                while True:
                    q = line.find('"', pos)
                    if q < 0:
                        field.append(line[pos:])
                        if i >= len(lines):  # an unclosed quote runs to the end
                            pos = len(line)
                            break
                        field.append("\n")  # a quoted field spans lines
                        line = lines[i]
                        i += 1
                        pos = 0
                        continue
                    field.append(line[pos:q])
                    pos = q + 1
                    if pos < len(line) and line[pos] == '"':
                        field.append('"')
                        pos += 1
                    elif pos >= len(line) or line[pos] == ",":
                        break
                    else:
                        field.append('"')
                record.append("".join(field))
            else:
                end = line.find(",", pos)
                record.append(line[pos:] if end < 0 else line[pos:end])
                if end < 0:
                    break
                pos = end
            if pos >= len(line):
                break
            pos += 1  # the comma
            if pos == len(line):
                record.append("")
                break
        yield record


def slug(header: str) -> str:
    """A payload key from a header: "Date (Excel)" is date_excel, "Oxygen Saturation
    [%]" is oxygen_saturation_pct. Deterministic, so a re-export with the same headers
    composes the same keys."""
    out: List[str] = []
    last_underscore = True  # no leading underscore
    for ch in header.strip().lower().replace("%", "pct"):
        if "a" <= ch <= "z" or "0" <= ch <= "9":
            out.append(ch)
            last_underscore = False
        elif not last_underscore:
            out.append("_")
            last_underscore = True
    return "".join(out).removesuffix("_")


def clean(cell: str) -> str:
    """A cell without the export's packaging, padding and surrounding quotes, and
    nothing else. The value inside is the source's."""
    v = cell.strip(" \t\r")
    if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        v = v[1:-1]
    return v


def payloads(path: Path) -> List[Dict[str, str]]:
    """One payload per reading in the export, in file order. An empty cell is left
    out, not written empty."""
    try:
        text = path.read_bytes().decode("utf-8", errors="replace")
    except FileNotFoundError as exc:
        raise ductile.Failure(f"no export at {path}", retry=False) from exc
    except OSError as exc:
        raise ductile.Failure(f"export {path}: {exc}", retry=True) from exc
    rows = list(records(text))
    if not rows:
        raise ductile.Failure(f"export {path} has no header row", retry=False)
    keys = [slug(h) for h in rows[0]]
    out: List[Dict[str, str]] = []
    ordinal: Dict[str, int] = {}
    for n, rec in enumerate(rows[1:], start=2):
        row = {}
        for key, cell in zip(keys, rec):
            v = clean(cell)
            if key and v:
                row[key] = v
        if not row:
            continue  # a blank line, not a reading
        ts = row.get("date_excel")
        if ts is None:
            raise ductile.Failure(f"export {path}: row {n} has no date_excel", retry=False)
        ordinal[ts] = ordinal.get(ts, 0) + 1
        row["reading"] = str(ordinal[ts])
        out.append(row)
    return out


# ZONE is where the app's wall clock reads, as the Definition's fact_time says.
ZONE = "Australia/Sydney"

# POSTURES maps the app's posture to Open mHealth's body_posture. Seated is the only
# one the app has written. Any other stays as the source's posture, which v4 does not
# admit, so the run stops for a person to name it rather than dropping it.
POSTURES = {"Seated": "sitting"}


def omh(row: Dict[str, str]) -> Dict[str, Any]:
    """A reading as an Open mHealth blood-pressure-4.0 body (anam card 83), with the
    export's own fields beside it. date_excel and reading stay, since identity and
    fact time point at them; every other field keeps the export's text. Location is
    not mapped: OMH distinguishes upper arm from wrist and the app does not say."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    at = datetime.strptime(row["date_excel"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(ZONE))
    body: Dict[str, Any] = {
        "systolic_blood_pressure": {"value": number(row["systolic"]), "unit": "mmHg"},
        "diastolic_blood_pressure": {"value": number(row["diastolic"]), "unit": "mmHg"},
        "effective_time_frame": {"date_time": at.isoformat()},
    }
    rest = {k: v for k, v in row.items() if k not in ("systolic", "diastolic")}
    posture = POSTURES.get(rest.get("posture", ""))
    if posture:
        body["body_posture"] = posture
        del rest["posture"]
    return {**body, **rest}


def number(text: str) -> Any:
    """The export's numeral as a JSON number: an integer when it has no fraction,
    so "137.0" is 137.0 and "137" is 137, nothing rounded."""
    return int(text) if text.lstrip("-").isdigit() else float(text)


def exported_on(path: Path) -> date:
    """The day an export was made: the date the app writes into its name
    (BloodPressure_9-October-2026), or the file's modification day when the name
    holds none."""
    try:
        return datetime.strptime(path.name.split("_", 1)[1], "%d-%B-%Y").date()
    except (IndexError, ValueError):
        return datetime.fromtimestamp(path.stat().st_mtime).date()


def exports(config: Dict[str, Any]) -> List[Path]:
    """Every export under export_dir, oldest first by exported_on, then by name.
    Order matters: on a resend the gate keeps the last payload it is sent for a
    reading, so the newest export, which holds any correction, is sent last."""
    root = Path(str(config["export_dir"]))
    if not root.is_dir():
        raise ductile.Failure(f"no export_dir at {root}", retry=False)
    pattern = str(config.get("pattern", DEFAULT_PATTERN))
    return sorted((p for p in root.rglob(pattern) if p.is_file()), key=lambda p: (exported_on(p), p.name, str(p)))


def identity(row: Dict[str, str]) -> Tuple[str, str]:
    """A reading's identity, as the Definition's identity_key composes it."""
    return row["date_excel"], row["reading"]


def newest(files: List[Path]) -> List[Tuple[Path, List[Dict[str, str]]]]:
    """Each export with the readings it is the newest holder of, oldest export
    first (files as exports orders them). A reading two exports hold is sent once,
    from the newer, so a correction stands and a resend is a no-op rather than a
    supersede back and forth."""
    seen: Set[Tuple[str, str]] = set()
    out: List[Tuple[Path, List[Dict[str, str]]]] = []
    for path in reversed(files):
        rows = [r for r in payloads(path) if identity(r) not in seen]
        seen.update(identity(r) for r in rows)
        out.append((path, rows))
    return out[::-1]


def batch_events(definitions: Dict[str, Definition], path: Path, rows: List[Dict[str, str]],
                 person: str) -> List[Dict[str, Any]]:
    """The readings of the export at path as batch events. Batches never span two
    exports, so no batch carries one reading twice."""
    definition = definitions[TYPE]
    envs = [envelope(definition, omh(p), asserted_person=person) for p in rows]
    check(definitions, envs)
    manifest = definition.body.decode()
    groups = list(batches(envs))
    return [
        ductile.event(BATCH_EVENT, {"envelopes": g, "definitions": [manifest], "batch": f"{path.name} {i + 1}/{len(groups)}"})
        for i, g in enumerate(groups)
    ]


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    event = ductile.payload_of(request)
    if event.get("change_type") == "deleted":
        return ductile.ok(f"{event.get('path')} was deleted: nothing to send")
    path = event.get("path")
    if not path:
        return ductile.error("the event names no path", retry=False)
    path = Path(str(path))
    rows = payloads(path)
    # An older export dropped in late must not undo a newer one's correction: with
    # export_dir known, readings a newer export holds are left to it.
    if config.get("export_dir"):
        files = exports(config)
        later = files[files.index(path) + 1:] if path in files else [f for f in files if exported_on(f) > exported_on(path)]
        held = {identity(r) for f in later for r in payloads(f)}
        rows = [r for r in rows if identity(r) not in held]
    events = batch_events(load(HERE), path, rows, str(config["person_id"]))
    readings = sum(len(e["payload"]["envelopes"]) for e in events)
    return ductile.ok(f"{readings} reading(s) of {path.name} in {len(events)} batch(es)", events=events)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    files = exports(config)
    events = [e for f, rows in newest(files) for e in batch_events(definitions, f, rows, str(config["person_id"]))]
    # Every export kept under export_dir together is everything the app has given us,
    # so poll's run is a snapshot. One export alone (handle) is not.
    if events:
        for ev, part in zip(events, snapshot_parts(len(events), [TYPE])):
            ev["payload"]["snapshot"] = part
    readings = sum(len(e["payload"]["envelopes"]) for e in events)
    return ductile.ok(f"{readings} reading(s) of {len(files)} export(s) in {len(events)} batch(es)", events=events)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    files = exports(config)
    events = [e for f in files for e in batch_events(definitions, f, payloads(f), "health-check")]
    readings = sum(len(e["payload"]["envelopes"]) for e in events)
    return ductile.ok(f"{readings} reading(s) in {len(files)} export(s), every one conforming to "
                      f"{TYPE} v{definitions[TYPE].version}")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
