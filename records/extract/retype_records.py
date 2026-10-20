#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""Rewrite the `type:` of every record in records files, per a rename table (anam cards 147, 191, 195).

The records importer sends each record under the type the file names, so after the
rename run carries the ledger over, the files on the Library share must name the new
types or the next poll is refused. This rewrites each record's `type` value in place,
as text, so nothing else in the file moves. Dry by default: it counts per type and
writes nothing without --yes.

    python3 -I records/extract/retype_records.py --table renames/taxonomy.json [--yes] <file-or-dir>...

The table is one of anam's `renames/`, the one its rename run used: `taxonomy.json` (card
147), `record-edge.json` (card 191), `kinds-segment.json` (card 196) or `vendor-leaves.json`
(card 195). {"renames": [{"from": ..., "to": ..., "select": {...}}, ...]}, select optional.

A row with a select (anam card 194) carries only the records it matches, as the rename
run does: `source` matches when it is "records", the source every records file's facets
come from, and `pointer` and `prefix` match when the record's field at the pointer is text
that starts with the prefix. The pointer names a top-level field, such as /id, since a
record's fields are its payload. Every record of a type split this way must match exactly
one row; a record that matches none or more than one is named and nothing is written.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml


def files_under(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.suffix in (".yaml", ".yml") and f.is_file())
        else:
            yield p


def load_table(path):
    """The table's rows, each checked: a select names a source, or a top-level pointer
    with a prefix, or both."""
    rows = json.loads(Path(path).read_text())["renames"]
    for i, r in enumerate(rows, start=1):
        s = r.get("select")
        if s is None:
            continue
        unknown = set(s) - {"source", "pointer", "prefix"}
        if unknown or not s or ("pointer" in s) != ("prefix" in s):
            raise SystemExit(f"rename {i}: a select names a source, or a pointer and a prefix, or both")
        if "pointer" in s and (not s["pointer"].startswith("/") or "/" in s["pointer"][1:] or "~" in s["pointer"]):
            raise SystemExit(f"rename {i}: pointer {s['pointer']!r} is not a top-level field such as /id")
    return rows


def field(record, pointer):
    """The text of the record's top-level field at pointer, or None when it holds none."""
    for key, value in record.value:
        if isinstance(key, yaml.ScalarNode) and key.value == pointer[1:]:
            return value.value if isinstance(value, yaml.ScalarNode) else None
    return None


def matches(row, typ, record):
    if row["from"] != typ:
        return False
    s = row.get("select")
    if s is None:
        return True
    if "source" in s and s["source"] != "records":
        return False
    if "pointer" not in s:
        return True
    text = field(record, s["pointer"])
    return text is not None and text.startswith(s["prefix"])


def records_of(text):
    """Each record's mapping node in a records file, in file order."""
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    if not isinstance(root, yaml.MappingNode):
        return []
    for key, value in root.value:
        if isinstance(key, yaml.ScalarNode) and key.value == "records" and isinstance(value, yaml.SequenceNode):
            return [r for r in value.value if isinstance(r, yaml.MappingNode)]
    return []


def retype(text, rows, counts, where):
    """text with each record's type rewritten, and the problems: a record of a type the
    table leaves that no row, or more than one, places."""
    edits, problems = [], []
    for record in records_of(text):
        node = next((v for k, v in record.value if isinstance(k, yaml.ScalarNode) and k.value == "type"), None)
        if not isinstance(node, yaml.ScalarNode):
            continue
        typ = node.value
        placed = [r for r in rows if matches(r, typ, record)]
        if not placed:
            if any(r["from"] == typ for r in rows):
                problems.append(f"{where}:{node.start_mark.line + 1}: {typ} {field(record, '/id')!r} matches no rename")
            continue
        if len(placed) > 1:
            problems.append(f"{where}:{node.start_mark.line + 1}: {typ} {field(record, '/id')!r} matches "
                            f"{len(placed)} renames")
            continue
        new = placed[0]["to"]
        counts[f"{typ} -> {new}"] += 1
        quote = node.style if node.style in ('"', "'") else ""
        edits.append((node.start_mark.index, node.end_mark.index, quote + new + quote))
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text, problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", required=True, help="the rename table, JSON")
    ap.add_argument("--yes", action="store_true", help="write the files; without it, only count")
    ap.add_argument("paths", nargs="+", help="records files, or directories of them")
    args = ap.parse_args()

    rows = load_table(args.table)
    counts: Counter = Counter()
    changed, problems = {}, []
    for f in files_under(args.paths):
        text = f.read_text()
        out, bad = retype(text, rows, counts, str(f))
        problems += bad
        if out != text:
            changed[f] = out
    for pair, n in sorted(counts.items()):
        print(f"{n:6d}  {pair}")
    for p in problems:
        print(p)
    if problems:
        print(f"{len(problems)} record(s) no one rename places; nothing written")
        return 1
    if args.yes:
        for f, out in changed.items():
            f.write_text(out)
    verb = "rewritten" if args.yes else "would change"
    print(f"{len(changed)} file(s) {verb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
