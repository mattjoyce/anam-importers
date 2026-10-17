---
type: workflow
title: Shape a blood pressure export
description: One CSV export dropped in a watched folder becomes batch events of health.blood-pressure envelopes, with the export's quirks absorbed and every payload validated before anything leaves.
timestamp: 2026-10-17T00:00:00Z
resource: bp_csv/run.py#handle
anchor: 'if event.get("change_type") == "deleted":'
basis: code
tier: core
trigger: The gateway's folder watcher sees a file named like BloodPressure_<date> under the export folder and emits an event with its path and change type. A pipeline runs anam_bp_csv handle on it.
steps:
  - actor: /components/importer-bp-csv.md
    caller: /components/ductile-gateway.md
    label: run handle on the dropped export
    action: "The event payload holds `path` and `change_type`. A deleted path returns an ok result with no events. A missing `path` is a non-retryable error."
    reads: [/data-structures/plugin-request.md]
    resource: bp_csv/run.py#handle
    anchor: 'if event.get("change_type") == "deleted":'
  - actor: /components/importer-bp-csv.md
    label: split the CSV into records
    action: "`records` reads quoted fields that span lines, doubled quotes and padded fields, line by line. A quoted field that never closes, or holds a quote that neither closes nor doubles, raises `Malformed` and the whole export is refused with nothing sent."
    resource: bp_csv/run.py#records
    anchor: 'raise Malformed(f"line {opened}: a quoted field is never closed")'
  - actor: /components/importer-bp-csv.md
    label: key cells by header, number readings
    action: "`slug` turns each header into a snake_case key and `clean` strips the export's packaging and nothing else. Empty cells are left out. Readings that share a timestamp get an ordinal in `reading`, which with `date_excel` is the identity."
    resource: bp_csv/run.py#payloads
    anchor: 'row["reading"] = str(ordinal[ts])'
  - actor: /components/importer-bp-csv.md
    label: leave readings a newer export holds
    action: "With `export_dir` configured, readings that a newer export also holds are dropped from this one, so an old export dropped late cannot undo a correction."
    resource: bp_csv/run.py#handle
    anchor: "held = {identity(r) for f in later for r in payloads(f)}"
  - actor: /components/importer-bp-csv.md
    label: shape each row to Open mHealth
    action: "`omh` builds systolic and diastolic as `{value, unit: mmHg}` and an `effective_time_frame` with the zone's offset in force on that date. Posture `Seated` becomes `sitting`. Every other export column stays as the source's text beside the body."
    resource: bp_csv/run.py#omh
    anchor: '"effective_time_frame": {"date_time": at.isoformat()},'
  - actor: /components/envelopes.md
    caller: /components/importer-bp-csv.md
    label: wrap the payload in an envelope
    action: "`envelope` returns the type, the Definition's version, the payload and `asserted_person`. It names no source and no source reference."
    writes: [/data-structures/envelope.md]
    resource: anam_importer/envelopes.py#envelope
    anchor: 'env["asserted_person"] = asserted_person'
  - actor: /components/envelopes.md
    caller: /components/importer-bp-csv.md
    label: validate against the Definition
    action: "`check` runs every payload through the Definition's closed schema and raises `Invalid` with every problem. An unmapped posture, a wrong unit or a missing field stops the run here, so a later refusal at the gate would mean the two sides disagree, not that a row was malformed."
    reads: [/data-structures/definition-manifest.md]
    resource: anam_importer/envelopes.py#check
    anchor: "raise Invalid(problems)"
  - actor: /components/envelopes.md
    caller: /components/importer-bp-csv.md
    label: cut into batches of at most 49
    action: "`batches` slices in order. Batches never span two exports, so no batch carries one reading twice."
    resource: anam_importer/envelopes.py#batches
    anchor: "for start in range(0, len(envelopes), size):"
  - actor: /components/importer-bp-csv.md
    label: emit one batch event per group
    action: "Each group becomes an `anam_bp_csv.batch` event with the envelopes, the Definition as text and a label `<file> i/n`. A `handle` run carries no snapshot label, because one export is not everything the app has given."
    writes: [/data-structures/batch-event.md]
    resource: bp_csv/run.py#batch_events
    anchor: '"batch": f"{path.name} {i + 1}/{len(groups)}"'
  - actor: /components/plugin-protocol.md
    caller: /components/importer-bp-csv.md
    label: write the one response
    action: "The handler's ok response, with the result line `N reading(s) of <file> in M batch(es)` and the events, is written to stdout. The gateway routes each event to `anam_submit` as in [submit a batch](/workflows/submit-a-batch.md)."
    writes: [/data-structures/plugin-response.md]
    ends: true
    resource: anam_importer/ductile.py#run
    anchor: "json.dump(response, sys.stdout)"
---

This is the typical importer in miniature. It reads a messy native format, absorbs the mess without altering a value, shapes to a standard vocabulary, and stops before sending anything it cannot validate. Re-running any step is safe, because a resend of an unchanged reading is a no-op at Anam.

What the trace shows that the code comments state in the abstract:

- The importer does the arithmetic of identity inputs (an ordinal) and none of identity itself.
- An export that cannot be read for certain is refused whole, because a partial send could later make a reading look absent.
- `poll` is the resend-everything form of the same path. It reads every export under `export_dir`, sends each reading once from its newest holder, and labels the run as a snapshot.
