---
type: component
title: anam_submit
description: The one generic plugin that posts a batch event to Anam under one importer's token, after storing any documents it names and making sure Anam publishes its Definitions.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/run.py#handle
anchor: "def handle(request: Dict[str, Any]) -> Dict[str, Any]:"
basis: code
tier: core
group: shared
depends_on:
  - /components/anam-client.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

It knows Anam's endpoints and nothing about any source. `handle` reads the batch from the triggering event, and `health` lists the Definitions Anam publishes, which proves the URL and the token. The gateway runs one instance per importer, each with its own `token_secret`, so an importer's token is reachable only by the plugin that posts with it.

Config keys are `anam_url` and `token_secret` (required) and `timeout`, `max_response_bytes` and `absent_ids_shown` (optional, range-checked). The manifest declares `maxItems: 49` on `envelopes`. A refused batch comes back as a non-retryable error that logs every envelope's reason. The events it emits are `anam.admitted` and `anam.snapshot_absent`, which pipelines route on. The full path is in [submit a batch](/workflows/submit-a-batch.md).
