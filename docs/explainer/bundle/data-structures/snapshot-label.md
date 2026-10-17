---
type: data-structure
title: Snapshot label
description: The small object a resend-everything run puts on every batch, with a run id, the part number, the part count and the facet types the run claims to cover.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#snapshot_parts
anchor: 'return [{"id": sid, "part": i + 1, "parts": count, "types": kinds} for i in range(count)]'
basis: code
tier: supporting
group: wire
references: []
---

`{id, part, parts, types}`. The id is `run-<uuid4>` and is fresh per run, which is what makes a run one snapshot. `types` is the sorted set of types the run carries, so for the records importer it lists only the types actually in the files, and a type whose every record was removed is not reported absent. See [Snapshot](/terms/snapshot.md).
