---
type: component
title: Record extractors (records/extract)
description: One-off scripts that turn an export that will never be sent again into a records file, deterministically, so a rerun on the same export writes the same records.
timestamp: 2026-10-17T00:00:00Z
resource: records/extract/strong_csv.py#main
anchor: "--max-session-sec"
basis: code
tier: detail
group: tools
depends_on:
  - /components/importer-records.md
---

Six scripts and a shared reader. `fitbit_weight.py` and `fitbit_sleep.py` read Fitbit workbooks (`xlsx.py` reads them with the standard library). `strong_csv.py` reads a workout app's CSV, `technogym_json.py` a gym equipment zip, `acl_pathology.py` pathology report PDFs through `pdftotext`, and `bp_diary_omh.py` reshapes blood pressure rows in a records file to Open mHealth.

They are not plugins and never touch Anam. A script writes records files into a folder, and the records importer sends them. Each takes `--out-dir`, and where the export carries local wall-clock time, `--zone`. `strong_csv.py` also takes `--max-session-sec` (default 10800), because that app leaves a workout open until the next begins; a different cap writes different records, and a resend supersedes. See [add a record extractor](/change-paths/add-a-record-extractor.md).
