---
type: term
title: Snapshot
description: A labelled set of batches that together claim to be everything a source holds of some types, letting Anam report what it holds live that the run did not carry.
timestamp: 2026-10-17T00:00:00Z
---

A resend-everything run labels its batches `{id, part, parts, types}` with `snapshot_parts`. When the last part is admitted, Anam compares what it holds live from that source for those types against what the run carried. Facets it holds but the run omitted are absent. The report only informs. See [an absent alert retracts nothing](/invariants/an-absent-alert-retracts-nothing.md).

A run that could not read part of the source (a file that would not decode, a line that would not parse, a payload over the size bound) must not claim to be a snapshot, or Anam would call the unread facets absent. Every importer that can skip input drops the label in that case. See [a snapshot claims everything](/invariants/a-snapshot-claims-everything.md).
