---
type: data-structure
title: Plugin manifest
description: The manifest.yaml in each plugin folder, which tells the gateway the plugin's commands, the events each emits, and its required and optional config keys.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/manifest.yaml#config_keys
anchor: "optional: [timeout, max_response_bytes, absent_ids_shown]"
basis: code
tier: detail
group: protocol
references: []
---

Every manifest has `manifest_spec: ductile.plugin`, `name`, `version`, `protocol: 2`, `entrypoint`, `commands` and `config_keys`. Each command carries a `type` (read or write), an input schema, and the events it emits with the payload values they carry. The `version` is the repository's single version, and `tests/test_version.py` fails if any manifest or the changelog's newest release disagrees. See [the repo has one version](/invariants/the-repo-has-one-version.md).
