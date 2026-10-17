---
type: data-structure
title: Envelope
description: The message Anam accepts, with the type, the Definition version, the payload, and an optional asserted person.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#envelope
anchor: '"definition_version": definition.version,'
basis: code
tier: supporting
group: wire
references:
  - to: /data-structures/definition-manifest.md
    how: shaped to
    card: "n:1"
---

| Field | Set by | Notes |
|---|---|---|
| `type` | `envelope` | the Definition's `facet_type` |
| `definition_version` | `envelope`, or `anam_submit` when `current_versions` is set | an integer; records and documents leave it out |
| `payload` | the importer | the source's data, validated by `check` against the Definition's schema |
| `asserted_person` | the importer | included only when it has a person to assert |

No source and no source reference. The records and documents importers build their dictionaries directly because they carry no Definition, and they follow the same shape.
