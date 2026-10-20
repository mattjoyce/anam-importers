---
type: invariant
title: A run claims to be a snapshot only when it read everything
description: An importer that skipped a file, a line, a result or an oversized payload sends its batches without a snapshot label, so Anam cannot call the unread facets absent.
timestamp: 2026-10-17T00:00:00Z
resource: garmin/run.py#run_over
anchor: "snapshot and shaped.complete"
basis: code
tier: supporting
enforced_at: garmin/run.py#run_over
enforced_anchor: "snapshot and shaped.complete"
applies_to:
  - /components/importer-garmin.md
  - /components/importer-concept2.md
  - /components/importer-owntracks.md
  - /components/importer-stays.md
  - /components/importer-dreamstation.md
  - /components/importer-links.md
tested_by:
  - tests/test_garmin.py#test_a_file_that_will_not_decode_is_logged_and_the_run_is_no_snapshot
  - tests/test_dreamstation.py#test_a_whole_card_is_a_snapshot_and_one_with_an_orphaned_events_file_is_not
---

Each importer states its own condition, the same idea in different words. Garmin checks that no FIT file failed, Concept2 that every cache file read, OwnTracks that no line or hour was skipped, stays the same, DreamStation that the decoder skipped no file, and links that no file went unread (a file read and excluded by the instance's rules, such as a note with no declared id, is reported and does not withhold the label). Only `poll`, the resend-everything command, can label a snapshot at all.
