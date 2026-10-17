---
type: component
title: Rebuild drill (scripts/rebuild-drill.py)
description: Starts a scratch Anam daemon on a new ledger, replays every importer's poll through anam_submit, and compares the result with a live daemon by facet id, content hash and status.
timestamp: 2026-10-17T00:00:00Z
resource: scripts/rebuild-drill.py#main
anchor: "def main() -> None:"
basis: code
tier: supporting
group: tools
depends_on:
  - /components/anam-submit.md
  - /components/anam-daemon.md
  - /components/importer-garmin.md
  - /components/importer-dreamstation.md
  - /components/importer-owntracks.md
---

The drill proves the importers alone can rebuild the record. A JSON plan lists each importer's source, folder and instance config, and any importer can be named in it, which is why the drill depends on all of them. `compare` prints, per type, the counts in each ledger and the facets only in one, and the ones whose hash or status differ, and `report.json` names each by `source_ref`. It only reads the live daemon. See [rebuild the record from the importers](/workflows/rebuild-the-record-from-the-importers.md) and `docs/rebuild-drill.md`.
