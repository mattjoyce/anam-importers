---
type: change-path
title: Add a record extractor
description: An export that will never be sent again gets a deterministic script under records/extract that writes a records file, and no importer.
timestamp: 2026-10-17T00:00:00Z
resource: records/extract/strong_csv.py#main
anchor: "--max-session-sec"
basis: docs
tier: detail
touches:
  - /components/record-extractors.md
  - /components/importer-records.md
  - /data-structures/records-file.md
---

1. **Script.** A Python script with a uv header for any dependency such as `pyyaml`, taking `--out-dir` and, for local times, `--zone`. It must be deterministic, so the same export writes the same records and ids.
2. **Records.** Each record has a `type`, a text `id` chosen once from the source's own stable key, and the payload fields verbatim. Reshaping to a new Definition version is a rerun with the same ids, which supersedes in place.
3. **Test.** Add a case to `tests/test_extract.py` with a small made-up export, and one that reads the output back through the records importer.
4. **Place the output** in the records folder and let `anam_records` send it.
