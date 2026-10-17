---
type: workflow
title: Send a records folder
description: Every YAML or JSON records file in a folder becomes envelopes of the Anam-bundled types they name, sent as one snapshot with versions stamped at submit time.
timestamp: 2026-10-17T00:00:00Z
resource: records/run.py#poll
anchor: 'paths, envs = scan(config, str(config["person_id"]))'
basis: code
tier: supporting
trigger: A folder watcher sees a records file appear or change under records_dir and runs handle, or a person runs poll. The two do the same thing, because a record may move between files.
steps:
  - actor: /components/record-extractors.md
    caller: outside
    label: write a records file from an export
    action: "For an export that will not be sent again, a person runs a script such as `strong_csv.py --out-dir DIR --zone ZONE`. It writes deterministic records into the folder, so a rerun on the same export writes the same files."
    writes: [/data-structures/records-file.md]
    resource: records/extract/strong_csv.py#main
    anchor: "--max-session-sec"
  - actor: /components/importer-records.md
    caller: /components/ductile-gateway.md
    label: scan the whole folder
    action: "`poll` calls `scan` with the folder and `person_id`. A missing folder is a non-retryable failure and an empty one is a state, nothing extracted yet."
    reads: [/data-structures/plugin-request.md]
    resource: records/run.py#poll
    anchor: 'paths, envs = scan(config, str(config["person_id"]))'
  - actor: /components/importer-records.md
    label: list the records files by name
    action: "Files directly under the folder with a `.yaml`, `.yml` or `.json` suffix, sorted by path. The suffixes are what a snapshot is made of, so they are not configurable."
    resource: records/run.py#files
    anchor: 'p.suffix.lower() in (".yaml", ".yml", ".json")'
  - actor: /components/importer-records.md
    label: compose YAML without resolving scalars
    action: "The loader drops PyYAML's implicit resolvers, so every scalar keeps its text and its quote style for the importer to resolve. Top-level keys outside `document`, `extracted` and `records` are refused."
    reads: [/data-structures/records-file.md]
    resource: records/run.py#_loader
    anchor: "Loader.yaml_implicit_resolvers = {}"
  - actor: /components/importer-records.md
    label: resolve plain scalars by Go rules
    action: "`resolve` maps nulls, booleans, Go-style integers (`0777` is 511, `1_000` is 1000) and floats, and keeps everything else as text. A quoted or block scalar is always text."
    resource: records/run.py#resolve
    anchor: "if text in _BOOLS:"
  - actor: /components/importer-records.md
    label: refuse a float Python writes differently
    action: "Anam keeps a number's text, so `number` checks that `json.dumps` of the float equals what Go would write. `0.00001` fails here and the error names the record."
    resource: records/run.py#number
    anchor: "would reach Anam as"
  - actor: /components/importer-records.md
    label: build envelopes, refuse duplicate rows
    action: "Each record's `type` goes to the envelope and its other fields become the payload, with `id` as text. All files are read before anything is sent, and two records claiming one identity are an error in the files, not a supersession."
    writes: [/data-structures/envelope.md]
    resource: records/run.py#scan
    anchor: "if key in seen:"
  - actor: /components/envelopes.md
    caller: /components/importer-records.md
    label: cut into batches of at most 49
    action: "The same `batches` as every importer. There is no `check` step here, because the importer carries no Definition. Anam validates against the type's current Definition at the gate."
    resource: anam_importer/envelopes.py#batches
    anchor: "raise ValueError(f\"batch size {size} is outside 1..{MAX_BATCH}\")"
  - actor: /components/importer-records.md
    label: label current versions and the snapshot
    action: "Each batch event sets `current_versions` and an empty `definitions` list. `snapshot_parts` labels the run with the sorted set of types the files actually carry, so a type whose records were all removed is not reported absent."
    writes: [/data-structures/batch-event.md, /data-structures/snapshot-label.md]
    resource: records/run.py#poll
    anchor: 'ev["payload"]["snapshot"] = part'
  - actor: /components/anam-submit.md
    caller: /components/ductile-gateway.md
    label: stamp each type's current version
    action: "`anam_submit` lists Anam's Definitions and fills `definition_version` on every envelope that has none, then submits as in [submit a batch](/workflows/submit-a-batch.md)."
    reads: [/data-structures/batch-event.md]
    ends: true
    resource: anam_submit/run.py#stamp_current
    anchor: 'env["definition_version"] = current[env["type"]]'
---

The records importer is the one that carries no Definitions, because the types it sends are bundled in Anam. That trades local validation for a dependency on Anam's current versions, and it is why the duplicate-identity guard lives here. A records folder is hand-written, and two files saying the same thing twice is a mistake worth stopping.

One-off exports reach this folder through the [extractors](/components/record-extractors.md). The extractors are deterministic, so rerunning one on the same export writes the same records and the resend is a no-op.
