---
type: data-structure
title: Plugin request
description: The one JSON object a plugin reads from stdin, naming a command and carrying the instance config, any granted secrets, and the triggering event.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/ductile.py#run
anchor: 'command = str(request.get("command", "")).strip().lower()'
basis: code
tier: supporting
group: protocol
references: []
---

| Field | Used by | Meaning |
|---|---|---|
| `command` | `run` | lower-cased and trimmed, then looked up in the handler map |
| `config` | every command | the instance config, read through the [config helpers](/components/config-helpers.md) |
| `secrets` | `anam_submit`, `fetch` | only the vault secrets the instance names, such as the token under `token_secret` |
| `event` | `handle` | `{type, payload}`, the event that triggered the run; `payload_of` returns its payload |

A request that is not a JSON object, or is invalid JSON, gets an error response with `retry` false.
