---
type: component
title: ductile gateway
description: The external supervisor that runs plugins on schedules and events, routes their events through pipelines, and hands each instance only the vault secrets its config names.
timestamp: 2026-10-17T00:00:00Z
resource: README.md#Wiring an importer into a gateway (Withings)
anchor: "## Wiring an importer into a gateway (Withings)"
basis: docs
tier: supporting
group: outside
depends_on:
  - /components/plugin-protocol.md
---

Not part of this repository. The README shows how a plugin is configured under it, with per-command timeouts, retries, schedules and a vault principal. This repository is a plugin root the gateway copies in, and `ductile plugin lock` pins a changed plugin. The gateway reads each plugin's `manifest.yaml` for its commands, its `config_keys` and the events it emits. See [ductile](/terms/ductile.md).
