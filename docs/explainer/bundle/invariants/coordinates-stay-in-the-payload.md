---
type: invariant
title: Coordinates stay in the payload
description: The OwnTracks and stays importers put positions only in envelope payloads, and their logs, result lines and event names carry counts, file names and line numbers.
timestamp: 2026-10-17T00:00:00Z
resource: owntracks/run.py#Read
anchor: "def logs(self) -> List[str]:"
basis: code
tier: supporting
enforced_at: owntracks/run.py#Read
enforced_anchor: "def logs(self) -> List[str]:"
applies_to:
  - /components/importer-owntracks.md
  - /components/importer-stays.md
tested_by:
  - tests/test_owntracks.py#test_no_coordinates_in_logs_or_results
---

The gateway logs a plugin's result and log lines, so these are where a location would leak. A bad spool line is logged as its file and line number, without its content. The stays importer's payload carries coordinates, as it must, and its logs do not.
