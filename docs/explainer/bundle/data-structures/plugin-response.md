---
type: data-structure
title: Plugin response
description: The one JSON object a plugin writes to stdout, either ok with a result line and events or error with a message and a retry flag, plus info log lines.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/ductile.py#ok
anchor: 'return {"status": "ok", "result": result, "events": events or [], "logs": _logs(logs)}'
basis: code
tier: supporting
group: protocol
references:
  - to: /data-structures/batch-event.md
    how: carries zero or more
    card: "1:n"
---

An ok response has `status`, `result` (one human line), `events` (each `{type, payload, dedupe_key?}`) and `logs` (each `{level: info, message}`). An error response has `status`, `error`, `retry` and `logs`. The events an importer emits are [batch events](/data-structures/batch-event.md), and `anam_submit` emits `anam.admitted` and `anam.snapshot_absent`.
