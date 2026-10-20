---
type: data-structure
title: Batch event
description: The ductile event an importer emits for each batch, named <plugin>.batch, carrying envelopes, the Definition manifests as text, a label, and optionally a snapshot label and documents.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/manifest.yaml#documents
anchor: "Optional, for record.document batches"
basis: code
tier: supporting
group: wire
references:
  - to: /data-structures/envelope.md
    how: carries up to 49
    card: "1:n"
  - to: /data-structures/definition-manifest.md
    how: carries as text
    card: "n:n"
  - to: /data-structures/snapshot-label.md
    how: may carry
    card: "n:1"
  - to: /data-structures/document-ref.md
    how: may name
    card: "1:n"
---

| Key | Type | Meaning |
|---|---|---|
| `envelopes` | list, at most 49 | the batch |
| `definitions` | list of text | the manifests the envelopes were shaped to; empty for records and documents |
| `batch` | text | a label such as `2/5`, `<file> 1/3` or `<type> 1/2`, carried to `anam.admitted` |
| `snapshot` | object | present on a resend-everything run |
| `documents` | list of `{path, file}` | present on `record.document` batches |
| `current_versions` | boolean | records and documents set it, so `anam_submit` stamps current versions |

The event type is `anam_<plugin>.batch` for each importer, for example `anam_withings.batch`. Definitions travel as text so the same event can be replayed to any Anam, which registers a type it does not hold.
