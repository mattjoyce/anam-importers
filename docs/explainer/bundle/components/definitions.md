---
type: component
title: Definitions (anam_importer.definitions)
description: Loads the Definition manifests in an importer's folder, validates payloads against their closed JSON Schema, and makes sure Anam publishes each one at its version before a batch is sent.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/definitions.py#ensure_published
anchor: "def ensure_published(client: Client, definitions: List[Definition]) -> None:"
basis: code
tier: supporting
group: shared
depends_on:
  - /components/anam-client.md
---

`load(folder)` reads `folder/definitions/*.json`, requires each file to be named for the type it declares, and refuses two manifests for one type. `Definition.errors(payload)` runs a Draft 2020-12 validator and returns every failure with its path, or nothing for a verbatim Definition with no schema. `jsonschema` is imported there and nowhere else, which is why plugins that validate carry it in their uv script header.

`ensure_published` asks Anam for each type and version. A missing one is registered. One held with a different body stops the run with a non-retryable error, because the importer and Anam disagree about what that version means. See [a held Definition version is never overwritten](/invariants/a-held-definition-version-is-never-overwritten.md).
