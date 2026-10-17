---
type: data-structure
title: Records file
description: A YAML or JSON file with a document, an extracted block and a list of records, each a facet type, an id and the payload fields.
timestamp: 2026-10-17T00:00:00Z
resource: records/run.py#FIELDS
anchor: 'FIELDS = ("document", "extracted", "records")'
basis: code
tier: supporting
group: sources
references:
  - to: /data-structures/envelope.md
    how: each record becomes
    card: "1:n"
---

Top-level keys are limited to `document` (the file the records came from), `extracted` (how) and `records`. A record's `type` goes to the envelope and the rest, including a text `id`, is the payload. `document` and `extracted` are provenance of the file, not of the fact, and are not sent. The folder must hold a file ending `.yaml`, `.yml` or `.json`, directly under `records_dir`, with at least one record.
