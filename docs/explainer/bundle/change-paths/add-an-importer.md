---
type: change-path
title: Add an importer
description: A new source is a folder with a manifest, a run.py that shapes payloads, and the Definitions it emits, plus a token line in Anam's importers file and an anam_submit instance in the gateway.
timestamp: 2026-10-17T00:00:00Z
resource: README.md#Writing an importer
anchor: "## Writing an importer"
basis: docs
tier: core
touches:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
  - /components/anam-submit.md
  - /data-structures/definition-manifest.md
  - /data-structures/batch-event.md
  - /data-structures/plugin-manifest.md
  - /workflows/submit-a-batch.md
  - /invariants/an-envelope-names-no-source.md
  - /invariants/a-snapshot-claims-everything.md
  - /invariants/config-is-read-and-checked-once-at-start.md
---

1. **Decide the type.** If Anam bundles a Definition for it, carry none and set `current_versions`, as the records importer does. Otherwise write `<folder>/definitions/<type>.json` in the manifest format, named for the type, with a closed schema, an `identity_key` and a `fact_time`. If an external standard fits (Open mHealth, IEEE 1752), follow it and name it in `source_schema`.
2. **Write the folder.** `manifest.yaml` with `protocol: 2`, `entrypoint: run.py`, the commands `handle`, `poll` and `health` and the events they emit, `config_keys`, and `version` equal to `VERSION`. `run.py` starts with a uv script header for `jsonschema` if it validates, puts the repository root on `sys.path`, and ends with `ductile.run({...})`.
3. **Shape only.** Read the source, build payloads, call `envelope`, `check` and `batches`, and emit one `anam_<plugin>.batch` event per batch with `envelopes`, `definitions` (the manifest as text) and a `batch` label. Compose no identity and send no source.
4. **Offer a resend-everything command.** `poll` sends all the source holds and labels the run with `snapshot_parts`, but only when it read everything. Raise `Failure(message, retry=...)` when the source fails, so the gateway knows whether another try can help.
5. **Config keys.** A limit, timeout, window or pattern is a key read and range-checked through `anam_importer.config` at the start of each command, with its default as a constant. See [add a config key](/change-paths/add-a-config-key.md).
6. **Tests.** Unit tests beside the others under `tests/` with invented data, a plugin run through `run_plugin`, and an `ANAM_BIN` test that admits once and resends as no-op.
7. **Token and gateway.** A token whose hash goes in Anam's importers file with the source and its types, an `anam_submit` instance with `token_secret`, a trigger, and pipelines from the trigger to the importer and from `<plugin>.batch` to the instance. Route `anam.snapshot_absent` to something that tells the operator.
8. **Release.** Add a changelog entry. Adding an importer is a minor version. See [release a new version](/change-paths/release-a-new-version.md).
