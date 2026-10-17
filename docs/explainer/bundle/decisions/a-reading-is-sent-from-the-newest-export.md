---
type: decision
title: A blood pressure reading is sent from the newest export that holds it
description: Exports overlap and later ones may correct a comment, so poll orders exports by the date in their name and sends each reading once, from its newest holder, and handle leaves readings a newer export holds.
timestamp: 2026-10-17T00:00:00Z
resource: bp_csv/run.py#newest
anchor: "def newest(files: List[Path])"
basis: code
tier: detail
alternatives:
  - Send every export in full, in order, which supersedes a corrected reading back and forth on each resend.
  - Keep only the newest export, which loses readings the app no longer includes.
affects:
  - /components/importer-bp-csv.md
tested_by:
  - tests/test_bp_csv.py#test_exports_go_oldest_first_by_the_date_in_their_name_and_a_reading_goes_once_from_the_newest
  - tests/test_bp_csv.py#test_an_older_export_dropped_late_leaves_a_newer_one_s_readings_alone
---

**Choice.** `exports` sorts by the date the app writes in the file name (the file's modification day when the name holds none), then by name. `newest` walks them from the newest back and keeps each identity once. `handle` with `export_dir` set also drops readings a later export holds.

**Why.** The gate keeps the last payload it is sent for an identity, so the order of a full resend decides which text stands. Sending the newest holder only makes a resend a no-op rather than a flip-flop, and a correction survives an old export dropped late.
