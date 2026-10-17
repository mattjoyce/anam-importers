---
type: component
title: anam_bp_csv
description: Shapes a blood pressure app's CSV exports to health.blood-pressure, an Open mHealth body beside the export's own text, sending each reading once from the newest export that holds it.
timestamp: 2026-10-17T00:00:00Z
resource: bp_csv/run.py#payloads
anchor: "def payloads(path: Path) -> List[Dict[str, str]]:"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

Source `bp-csv`, type `health.blood-pressure` v5, identity `/date_excel` with `/reading`, fact time `/date_excel` in Australia/Sydney. `handle` takes a file event with a path, `poll` resends every export under `export_dir` matching the `pattern` key (default `BloodPressure_*`).

The export is messy and the importer absorbs it without touching a value. `records` splits CSV the way Go's `encoding/csv` does with leading space trimmed. A quoted field that never closes, or holds a quote that neither closes nor doubles, makes the whole export `Malformed` and nothing of it is sent, because a reading swallowed into another's comment would later be reported absent. Several readings can share one timestamp, so each gets an ordinal `reading` within its timestamp, which is half the identity.

`omh` builds the Open mHealth blood-pressure body (systolic and diastolic with unit `mmHg`, an offset-bearing `effective_time_frame`, posture `Seated` mapped to `sitting`) and keeps every export column as text beside it. `newest` sends a reading held by two exports only from the newer one, so a corrected comment stands and a resend is a no-op. See [sending the newest holder of a reading](/decisions/a-reading-is-sent-from-the-newest-export.md).
