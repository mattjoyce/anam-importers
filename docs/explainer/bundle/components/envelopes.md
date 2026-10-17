---
type: component
title: Envelopes (anam_importer.envelopes)
description: Builds an envelope from a payload, checks every payload against its Definition before anything leaves, cuts envelopes into batches of at most 49, and labels a resend as snapshot parts.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#envelope
anchor: "def envelope("
basis: code
tier: core
group: shared
depends_on:
  - /components/definitions.md
---

Four functions and one constant. `envelope(definition, payload, asserted_person)` returns `{type, definition_version, payload}` and adds `asserted_person` only when given. `check(definitions, envelopes)` raises `Invalid` carrying every problem, so the importer finds all its mistakes in one run. `batches(envelopes, size=MAX_BATCH)` yields slices in order and refuses a size outside 1 to 49. `snapshot_parts(count, types, run_id)` returns one label per batch with a fresh `run-<uuid4>` id unless one is given.

The records and documents importers build their envelopes without a version and set `current_versions` on the batch, so `anam_submit` stamps the version Anam publishes. See [validate before anything leaves](/invariants/validate-before-anything-leaves.md).
