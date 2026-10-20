---
type: data-structure
title: Sidecar file
description: The <file>.meta.yaml beside a document, a mapping with a required date and optional title, note and other fields that become part of the record.document payload.
timestamp: 2026-10-17T00:00:00Z
resource: documents/run.py#sidecar
anchor: "def sidecar(path: Path) -> Dict[str, Any]:"
basis: code
tier: detail
group: sources
references:
  - to: /data-structures/document-ref.md
    how: starts the payload of the envelope that pairs with
    card: "1:1"
---

`date` must be a non-empty string, written `YYYY-MM-DD`. The keys `path`, `sha256`, `bytes` and `media_type` are refused, because the file decides them. The mapping is read with the records importer's YAML reader.
