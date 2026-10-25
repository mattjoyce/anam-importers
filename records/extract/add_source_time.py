#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Give every record of the types Anam requires source_time for a source_time block (anam card 198).

health.weight, health.lab-result, health.lab-panel, health.blood-pressure,
health.encounter and health.donation read hand-made records files, and each of
their Definitions requires source_time at its current version. This reads a
folder of records files and writes, to a staging folder, a copy of each file that
holds any of those records, with the block added:

    source_time:
      value: '2026-01-24 06:30'      # the fact-time field's text, as written
      zone: Australia/Sydney
      offset: '+11:00'               # health.weight only: the offset its wall clock had
      basis: source

The files state the zone, so the basis is source (Matt, 2026-10-26). The change is
textual: the block is inserted under the fact-time field's line and nothing else in
the file moves, so a diff of the original against the copy is those lines alone. A
record that already carries a source_time in Australia/Sydney with basis assumption
(the first extractions) has that one word changed to source; any other existing
block stops the run for a person to look at. A record whose report printed no time
(time_unknown: true) is given its date alone as the value, as the report printed it.

A wall clock Sydney skips or repeats (a daylight-saving gap or overlap) names no one
instant, so the script stops on it and names the record, never picking a side. It
writes no file that holds one, lists every such record, and exits 1. Dry by default:
it counts per type and writes nothing without --out.

    python3 -I records/extract/add_source_time.py [--out DIR] <records-dir>

With --out it also writes MANIFEST.txt there: for each staged file, the sha256 of the
original and of the copy, so a person can see before swapping that the live file has
not changed since it was staged.

    python3 -I records/extract/add_source_time.py --verify STAGED_DIR <records-dir>

checks a staging folder against the originals: every original is still the one the
manifest hashed, the staged file differs from it only by the added blocks (and the
one word of an existing block), parses to the same records plus source_time, and
every target record in it carries a correct block. Exit 1 on any problem.
"""
import argparse
import hashlib
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from anam_importer import clock  # noqa: E402

ZONE = "Australia/Sydney"
BASIS = "source"

# TIMED is each type's fact-time field and its layout, as the Definitions read them. Not
# configurable: it restates the bundled Definitions' time_semantics.
TIMED = {
    "health.weight": ("date", "%Y-%m-%d %H:%M"),
    "health.lab-result": ("collected", "%Y-%m-%d %H:%M"),
    "health.lab-panel": ("collected", "%Y-%m-%d %H:%M"),
    "health.blood-pressure": ("date_excel", "%Y-%m-%d %H:%M:%S"),
    "health.encounter": ("date", "%Y-%m-%d %H:%M"),
    "health.donation": ("date", "%Y-%m-%d %H:%M"),
}
# WITH_OFFSET are the types whose Definition reads the fact time at source_time's offset.
WITH_OFFSET = {"health.weight"}

RECORD_START = re.compile(r"^- ")
KEY = re.compile(r"^  ([A-Za-z_][\w-]*):(?: (.*))?$")


class Stop(Exception):
    """A record the script will not guess at."""


def block(typ: str, shown: str, wall: datetime) -> list:
    """The source_time lines for one record, indented as a record's field."""
    out = ["  source_time:", f"    value: '{shown}'", f"    zone: {ZONE}"]
    if typ in WITH_OFFSET:
        out.append(f"    offset: '{clock.offset_text(clock.local_instant(wall, ZONE).utcoffset())}'")
    out.append(f"    basis: {BASIS}")
    return out


def records_of(path: Path) -> list:
    data = yaml.safe_load(path.read_text())
    return data.get("records", []) if isinstance(data, dict) else []


def chunks(lines: list) -> list:
    """Line index ranges of each record under `records:`, in order."""
    starts = [i for i, ln in enumerate(lines) if RECORD_START.match(ln)]
    return [(s, e) for s, e in zip(starts, starts[1:] + [len(lines)])]


def rewrite_existing(lines: list, lo: int, hi: int, rec: dict, where: str) -> bool:
    """A record that already has source_time: assumption in Sydney becomes source.
    Returns True when it did; anything else already there stops the run."""
    st = rec["source_time"]
    if st.get("zone") != ZONE or st.get("basis") not in ("assumption", BASIS):
        raise Stop(f"{where}: already has source_time {st}; not touched")
    if st["basis"] == BASIS:
        return False
    for i in range(lo, hi):
        if re.match(r"^    basis: assumption\s*$", lines[i]):
            lines[i] = "    basis: source"
            return True
    raise Stop(f"{where}: source_time basis is assumption but its line was not found")


def plan_record(lines: list, lo: int, hi: int, rec: dict, where: str, counts: Counter):
    """What one target record needs: None when it needs nothing or its existing block
    was edited in place, else (line to insert at, the block's lines). Raises Stop,
    ClockError or ValueError for a record the script will not guess at."""
    typ = rec["type"]
    key, layout = TIMED[typ]
    if "source_time" in rec:
        changed = rewrite_existing(lines, lo, hi, rec, where)
        counts[(typ, "basis changed" if changed else "already source")] += 1
        return None
    shown = str(rec[key])
    wall = datetime.strptime(shown, layout)
    if rec.get("time_unknown"):
        shown = shown.split(" ")[0]
    at = next((i for i in range(lo, hi) if (m := KEY.match(lines[i])) and m.group(1) == key), None)
    if at is None:
        raise Stop(f"{where}: no `{key}:` line at the record's top level")
    counts[(typ, "block added")] += 1
    return at + 1, block(typ, shown, wall)


def stage(path: Path, counts: Counter, stops: list):
    """The file's text with the blocks added, or None when it needs no change or any
    record stopped (each is named in stops)."""
    recs = records_of(path)
    if not any(r.get("type") in TIMED for r in recs):
        return None
    lines = path.read_text().split("\n")
    spans = chunks(lines)
    if len(spans) != len(recs):
        raise SystemExit(f"{path.name}: {len(recs)} records but {len(spans)} list items in the text")
    edits, before, bad = [], Counter(counts), False
    for (lo, hi), rec in zip(spans, recs):
        if rec.get("type") not in TIMED:
            continue
        where = f"{path.name} {rec.get('id')}"
        try:
            plan = plan_record(lines, lo, hi, rec, where, counts)
        except (Stop, clock.ClockError, ValueError, KeyError) as exc:
            stops.append(f"{where}: {exc}")
            bad = True
            continue
        if plan:
            edits.append(plan)
    if bad or counts == before:
        return None
    for at, new in sorted(edits, reverse=True):
        lines[at:at] = new
    return "\n".join(lines)


def line_diff_is_blocks_only(old: list, new: list) -> list:
    """Problems in the line diff of old to new: only added source_time blocks, and
    `basis: assumption` lines turned to `basis: source`, may differ. One pass, since
    nothing but insertions and that one word may differ."""
    problems, i, j = [], 0, 0
    while j < len(new):
        if i < len(old) and new[j] == old[i]:
            i, j = i + 1, j + 1
        elif i < len(old) and old[i] == "    basis: assumption" and new[j] == "    basis: source":
            i, j = i + 1, j + 1
        elif new[j] == "  source_time:":
            j += 1
            while j < len(new) and new[j].startswith("    "):
                j += 1
        else:
            return problems + [f"line {j + 1} of the staged file: {new[j]!r} is not an added block"]
    if i != len(old):
        problems.append(f"line {i + 1} of the original is missing from the staged file")
    return problems


def check_block(rec: dict, where: str) -> list:
    typ = rec["type"]
    key, layout = TIMED[typ]
    st = rec.get("source_time")
    if not isinstance(st, dict):
        return [f"{where}: no source_time"]
    want_keys = {"value", "zone", "basis"} | ({"offset"} if typ in WITH_OFFSET else set())
    if set(st) != want_keys or st["zone"] != ZONE or st["basis"] != BASIS:
        return [f"{where}: source_time {st} is not {ZONE} / {BASIS} with {sorted(want_keys)}"]
    text = str(rec[key])
    if str(st["value"]) != (text.split(" ")[0] if rec.get("time_unknown") else text):
        return [f"{where}: value {st['value']!r} is not the field's text {text!r}"]
    if typ in WITH_OFFSET:
        want = clock.offset_text(clock.local_instant(datetime.strptime(text, layout), ZONE).utcoffset())
        if st["offset"] != want:
            return [f"{where}: offset {st['offset']} but {text} in {ZONE} is {want}"]
    return []


def verify(records_dir: Path, staged_dir: Path) -> list:
    """Every problem found staging staged_dir against records_dir; empty means sound."""
    problems = []
    manifest = {}
    for row in (staged_dir / "MANIFEST.txt").read_text().split("\n"):
        if row:
            name, orig, new = row.split(" ")
            manifest[name] = (orig.split("=")[1], new.split("=")[1])
    on_disk = {p.name for p in staged_dir.glob("*.yaml")}
    if on_disk != set(manifest):
        problems.append(f"staged files {sorted(on_disk ^ set(manifest))} are not in step with the manifest")
    for name, (orig_sum, new_sum) in sorted(manifest.items()):
        orig, new = records_dir / name, staged_dir / name
        if hashlib.sha256(orig.read_bytes()).hexdigest() != orig_sum:
            problems.append(f"{name}: the original has changed since it was staged")
        if hashlib.sha256(new.read_bytes()).hexdigest() != new_sum:
            problems.append(f"{name}: the staged file has changed since it was written")
        problems += [f"{name}: {p}" for p in line_diff_is_blocks_only(orig.read_text().split("\n"), new.read_text().split("\n"))]
        old_recs, new_recs = records_of(orig), records_of(new)
        if len(old_recs) != len(new_recs):
            problems.append(f"{name}: {len(old_recs)} records became {len(new_recs)}")
            continue
        for o, n in zip(old_recs, new_recs):
            where = f"{name} {n.get('id')}"
            if n.get("type") in TIMED:
                try:
                    problems += check_block(n, where)
                except (ValueError, clock.ClockError, KeyError) as exc:
                    problems.append(f"{where}: {exc}")
            if {k: v for k, v in o.items() if k != "source_time"} != {k: v for k, v in n.items() if k != "source_time"}:
                problems.append(f"{where}: a field other than source_time differs")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("records_dir", type=Path)
    ap.add_argument("--out", type=Path, help="write the changed files here (never the records folder itself)")
    ap.add_argument("--verify", type=Path, metavar="STAGED_DIR", help="check a staging folder against records_dir and write nothing")
    args = ap.parse_args(argv)
    if args.verify:
        problems = verify(args.records_dir, args.verify)
        for p in problems:
            print(f"PROBLEM {p}", file=sys.stderr)
        print(f"{len(problems)} problems")
        return 1 if problems else 0
    if args.out and args.out.resolve() == args.records_dir.resolve():
        raise SystemExit("--out must not be the records folder")
    counts, stops, staged = Counter(), [], []
    for path in sorted(args.records_dir.glob("*.yaml")):
        new = stage(path, counts, stops)
        if new is not None:
            staged.append((path, new))
    for (typ, what), n in sorted(counts.items()):
        print(f"{typ:24} {what:16} {n}")
    print(f"{len(staged)} files change")
    for s in stops:
        print(f"STOP {s}", file=sys.stderr)
    if args.out:
        args.out.mkdir(parents=True, exist_ok=True)
        manifest = []
        for path, new in staged:
            (args.out / path.name).write_text(new)
            before = hashlib.sha256(path.read_bytes()).hexdigest()
            after = hashlib.sha256(new.encode()).hexdigest()
            manifest.append(f"{path.name} original={before} staged={after}")
        (args.out / "MANIFEST.txt").write_text("\n".join(manifest) + "\n")
    return 1 if stops else 0


if __name__ == "__main__":
    sys.exit(main())
