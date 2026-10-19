#!/usr/bin/env python3
"""Rewrite the `type:` of every record in records files, per a rename table (anam card 147).

The records importer sends each record under the type the file names, so after the
rename run carries the ledger over, the files on the Library share must name the new
types or the next poll is refused. This rewrites `type: <old>` lines in place, as text,
so nothing else in the file moves. Dry by default: it counts per type and writes
nothing without --yes.

    python3 -I records/extract/retype_records.py --table renames/taxonomy.json [--yes] <file-or-dir>...

The table is anam's `renames/taxonomy.json`: {"renames": [{"from": ..., "to": ...}, ...]}.
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path


def files_under(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            yield from sorted(f for f in p.rglob("*") if f.suffix in (".yaml", ".yml") and f.is_file())
        else:
            yield p


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--table", required=True, help="the rename table, JSON")
    ap.add_argument("--yes", action="store_true", help="write the files; without it, only count")
    ap.add_argument("paths", nargs="+", help="records files, or directories of them")
    args = ap.parse_args()

    table = {p["from"]: p["to"] for p in json.loads(Path(args.table).read_text())["renames"]}
    line = re.compile(r"^(\s*-?\s*type:\s*)([A-Za-z0-9.-]+)(\s*(?:#.*)?)$", re.M)
    counts: Counter = Counter()
    changed = 0
    for f in files_under(args.paths):
        text = f.read_text()

        def swap(m):
            old = m.group(2)
            new = table.get(old)
            if new is None:
                return m.group(0)
            counts[f"{old} -> {new}"] += 1
            return m.group(1) + new + m.group(3)

        out = line.sub(swap, text)
        if out != text:
            changed += 1
            if args.yes:
                f.write_text(out)
    for pair, n in sorted(counts.items()):
        print(f"{n:6d}  {pair}")
    verb = "rewritten" if args.yes else "would change"
    print(f"{changed} file(s) {verb}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
