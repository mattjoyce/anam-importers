---
type: component
title: anam_records
description: Sends a folder of YAML or JSON records files as one snapshot of the Anam-bundled types they carry, resolving YAML scalars by Go yaml.v3 rules instead of YAML 1.1.
timestamp: 2026-10-17T00:00:00Z
resource: records/run.py#scan
anchor: "def scan(config: Dict[str, Any], person: str)"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/plugin-protocol.md
---

Source `records`. It carries no Definitions, because every type a records file names is bundled in Anam. A file names no version, so each batch sets `current_versions` and `anam_submit` stamps the type's current one.

`handle` runs the same as `poll`, since a record may move between files and one file alone cannot be checked for duplicates. `scan` reads every file in `records_dir` with a `.yaml`, `.yml` or `.json` suffix, in name order, and refuses the whole run if two records claim one identity across files and types. Because `IDENTITY` restates only the blood pressure key and defaults to `id` otherwise, this check is a local guard and the gate composes the real identity.

Scalars resolve as Go's yaml.v3 does, not YAML 1.1. `yes` is text, `0777` is 511, `1_000` is 1000, a date stays the text written, and a quoted scalar is always text. A float whose Python rendering would differ from Go's (`0.00001`) stops the run and names the record, since Anam keeps a number's text and another rendering would supersede the facet. Duplicate keys, unknown top-level fields and explicit tags are refused.
