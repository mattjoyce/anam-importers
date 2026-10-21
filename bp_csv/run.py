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

import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, NamedTuple, Set, Tuple
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import clock as clk  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

TYPE = "health.blood-pressure"
BATCH_EVENT = "anam_bp_csv.batch"

# DEFAULT_PATTERN matches the app's export names, unless config's pattern says
# otherwise. The name changes with every export, and nothing about identity is read
# from it.
DEFAULT_PATTERN = "BloodPressure_*"


class Malformed(ValueError):
    """An export whose record boundaries cannot be read for certain. Nothing of it is
    sent: a reading swallowed into another's comment would be reported absent."""


def records(text: str) -> Iterator[Tuple[int, List[str]]]:
    """The export's records, each with the line it starts on, split as Go's
    encoding/csv splits them with TrimLeadingSpace, which is how the built-in worker
    read it.

    Leading whitespace of a field is dropped, so a field the export pads before its
    opening quote is still a quoted field. Inside one, "" is a quote, and a field may
    span lines. A blank line is no record. CRLF is LF. The worker also read with
    LazyQuotes, keeping a quote that neither closes the field nor doubles; that is how
    a comment that lost its closing quote swallows the next reading, so here it is
    Malformed, as is a quote still open at the end (anam card 114).
    """
    lines = text.replace("\r\n", "\n").split("\n")
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        start = i
        if line == "":
            continue
        record: List[str] = []
        pos = 0
        while True:
            while pos < len(line) and line[pos].isspace():
                pos += 1
            if pos < len(line) and line[pos] == '"':
                pos += 1
                opened = i
                field: List[str] = []
                while True:
                    q = line.find('"', pos)
                    if q < 0:
                        field.append(line[pos:])
                        if i >= len(lines):
                            raise Malformed(f"line {opened}: a quoted field is never closed")
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
                        raise Malformed(f"line {opened}: a quoted field holds a quote, on line {i}, that neither "
                                        "closes it nor doubles")
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
        yield start, record


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
    try:
        rows = list(records(text))
    except Malformed as exc:
        raise ductile.Failure(f"export {path}: {exc}; nothing of it is sent", retry=False) from exc
    if not rows:
        raise ductile.Failure(f"export {path} has no header row", retry=False)
    keys = [slug(h) for h in rows[0][1]]
    out: List[Dict[str, str]] = []
    ordinal: Dict[str, int] = {}
    for n, rec in rows[1:]:
        if len(rec) != len(keys):
            raise ductile.Failure(f"export {path}: line {n} has {len(rec)} fields and the header {len(keys)}; "
                                  "nothing of it is sent", retry=False)
        row = {}
        for key, cell in zip(keys, rec):
            v = clean(cell)
            if key and v:
                row[key] = v
        if not row:
            continue  # a blank line, not a reading
        ts = row.get("date_excel")
        if ts is None:
            raise ductile.Failure(f"export {path}: line {n} has no date_excel", retry=False)
        ordinal[ts] = ordinal.get(ts, 0) + 1
        row["reading"] = str(ordinal[ts])
        out.append(row)
    return out


# ZONE is where the Definition reads the app's wall clock, date_excel, in its
# fact_time; it is read from there so it is stated once.
ZONE = json.loads((HERE / "definitions" / f"{TYPE}.json").read_text())["meta"]["time_semantics"]["fact_time"]["zone"]


class Clock(NamedTuple):
    """The zone the cuff's wall clock is read in, and who said so (anam card 198)."""

    zone: str
    basis: str


# ASSUMED is the clock when config names no zone: the Definition's, which is an
# assumption, and each run that reads by it says so.
ASSUMED = Clock(ZONE, "assumption")


def clock_of(config: Dict[str, Any]) -> Clock:
    """config's zone, the zone a person says the cuff's clock is set to, checked:
    read once, at the start of a command. The Definition reads date_excel in ZONE
    and a Definition's fact-time rule never changes, so a zone other than ZONE would
    place every reading at an instant its source_time denies. Until a fact can name
    its own zone (anam card 198's decision for Matt), only ZONE can be named."""
    if "zone" not in config:
        return ASSUMED
    zone = cfg.text(config, "zone", ZONE)
    try:
        clk.check_zone(zone)
    except ValueError as exc:
        raise cfg.bad("zone", str(exc)) from exc
    if zone != ZONE:
        raise cfg.bad("zone", f"{zone!r}: {TYPE} reads date_excel in {ZONE}, so a cuff set to another zone "
                              "cannot be placed truly until a fact can name its own zone")
    return Clock(zone, "configuration")

# POSTURES maps the app's posture to Open mHealth's body_posture. Seated is the only
# one the app has written. Any other stays as the source's posture, which v4 does not
# admit, so the run stops for a person to name it rather than dropping it. Not
# configurable: it is what the words mean, and a change rewrites the facets.
POSTURES = {"Seated": "sitting"}


def omh(row: Dict[str, str], clock: Clock = ASSUMED) -> Dict[str, Any]:
    """A reading as an Open mHealth blood-pressure-4.0 body (anam card 83), with the
    export's own fields beside it. date_excel and reading stay, since identity and
    fact time point at them; every other field keeps the export's text. Location is
    not mapped: OMH distinguishes upper arm from wrist and the app does not say.
    source_time says date_excel was read in clock's zone, and why (anam card 198).
    A wall clock the zone skips or repeats is a ClockError: no instant can be said
    for it without a guess."""
    wall = datetime.strptime(row["date_excel"], "%Y-%m-%d %H:%M:%S")
    at = clk.local_instant(wall, clock.zone)
    body: Dict[str, Any] = {
        "systolic_blood_pressure": {"value": number(row["systolic"]), "unit": "mmHg"},
        "diastolic_blood_pressure": {"value": number(row["diastolic"]), "unit": "mmHg"},
        "effective_time_frame": {"date_time": at.isoformat()},
        "source_time": clk.source_time(row["date_excel"], clock.zone, clock.basis),
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


def exported_on(path: Path, zone: str = ZONE) -> date:
    """The day an export was made: the date the app writes into its name
    (BloodPressure_9-October-2026), or the file's modification day when the name
    holds none, the day in zone, the cuff's, as the app's own name is. Never the
    host's zone: it orders resends, so it must not move with the gateway."""
    try:
        return datetime.strptime(path.name.split("_", 1)[1], "%d-%B-%Y").date()
    except (IndexError, ValueError):
        return datetime.fromtimestamp(path.stat().st_mtime, ZoneInfo(zone)).date()


def pattern_of(config: Dict[str, Any]) -> str:
    """pattern, checked: read once, at the start of a command."""
    return cfg.text(config, "pattern", DEFAULT_PATTERN)


def exports(config: Dict[str, Any], pattern: str, zone: str = ZONE) -> List[Path]:
    """Every export under export_dir that pattern names, oldest first by
    exported_on, then by name. Order matters: on a resend the gate keeps the last
    payload it is sent for a reading, so the newest export, which holds any
    correction, is sent last."""
    root = Path(str(config["export_dir"]))
    if not root.is_dir():
        raise ductile.Failure(f"no export_dir at {root}", retry=False)
    return sorted((p for p in root.rglob(pattern) if p.is_file()), key=lambda p: (exported_on(p, zone), p.name, str(p)))


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


class Shaped(NamedTuple):
    """An export's batch events, and a log line per reading left out."""

    events: List[Dict[str, Any]]
    skipped: List[str]


def batch_events(definitions: Dict[str, Definition], path: Path, rows: List[Dict[str, str]],
                 person: str, clock: Clock) -> Shaped:
    """The readings of the export at path as batch events. Batches never span two
    exports, so no batch carries one reading twice. A reading whose wall clock the
    zone skips or repeats is left out with a log line."""
    definition = definitions[TYPE]
    envs, skipped = [], []
    for p in rows:
        try:
            envs.append(envelope(definition, omh(p, clock), asserted_person=person))
        except clk.ClockError as exc:
            skipped.append(f"skipped {path.name} reading {p['date_excel']} #{p['reading']}: {exc}")
    check(definitions, envs)
    manifests = definitions.manifests()
    groups = list(batches(envs))
    return Shaped([
        ductile.event(BATCH_EVENT, {"envelopes": g, "definitions": manifests, "batch": f"{path.name} {i + 1}/{len(groups)}"})
        for i, g in enumerate(groups)
    ], skipped)


def clock_logs(clock: Clock) -> List[str]:
    """What a run says about the zone it read the cuff's clock in."""
    if clock.basis == "assumption":
        return [f"readings are read as {clock.zone} wall clock (basis assumption): set zone to say the cuff's zone"]
    return []


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    pattern = pattern_of(config)
    clock = clock_of(config)
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
        files = exports(config, pattern, clock.zone)
        later = files[files.index(path) + 1:] if path in files else [
            f for f in files if exported_on(f, clock.zone) > exported_on(path, clock.zone)]
        held = {identity(r) for f in later for r in payloads(f)}
        rows = [r for r in rows if identity(r) not in held]
    shaped = batch_events(load(HERE), path, rows, str(config["person_id"]), clock)
    readings = sum(len(e["payload"]["envelopes"]) for e in shaped.events)
    return ductile.ok(f"{readings} reading(s) of {path.name} in {len(shaped.events)} batch(es)", events=shaped.events,
                      logs=shaped.skipped + clock_logs(clock))


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    pattern = pattern_of(config)
    clock = clock_of(config)
    definitions = load(HERE)
    files = exports(config, pattern, clock.zone)
    shaped = [batch_events(definitions, f, rows, str(config["person_id"]), clock) for f, rows in newest(files)]
    events = [e for s in shaped for e in s.events]
    skipped = [line for s in shaped for line in s.skipped]
    # Every export kept under export_dir together is everything the app has given us,
    # so poll's run is a snapshot, unless a reading was left out. One export alone
    # (handle) is not.
    if events and not skipped:
        for ev, part in zip(events, snapshot_parts(len(events), [TYPE])):
            ev["payload"]["snapshot"] = part
    readings = sum(len(e["payload"]["envelopes"]) for e in events)
    summary = f"{readings} reading(s) of {len(files)} export(s) in {len(events)} batch(es)"
    if skipped:
        summary += f"; no snapshot: {len(skipped)} reading(s) left out"
    return ductile.ok(summary, events=events, logs=skipped + clock_logs(clock))


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    pattern = pattern_of(config)
    clock = clock_of(config)
    definitions = load(HERE)
    files = exports(config, pattern, clock.zone)
    shaped = [batch_events(definitions, f, payloads(f), "health-check", clock) for f in files]
    readings = sum(len(e["payload"]["envelopes"]) for s in shaped for e in s.events)
    skipped = [line for s in shaped for line in s.skipped]
    return ductile.ok(f"{readings} reading(s) in {len(files)} export(s), every one conforming to "
                      f"{TYPE} v{definitions[TYPE].version}, read in {clock.zone} (basis {clock.basis}); "
                      f"{len(skipped)} left out", logs=skipped + clock_logs(clock))


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
