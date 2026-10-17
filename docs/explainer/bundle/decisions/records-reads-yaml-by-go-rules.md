---
type: decision
title: Records are read with Go yaml.v3 scalar rules
description: The records and documents importers resolve YAML scalars as Go yaml.v3 does, not as YAML 1.1, so the payload text of a number or a date does not change with the reader.
timestamp: 2026-10-17T00:00:00Z
resource: records/run.py#resolve
anchor: "def resolve(text: str) -> Any:"
basis: code
tier: detail
alternatives:
  - PyYAML's default loader, which reads yes as true, 0777 as 511 and a bare date as a date object.
  - Quote everything in the files, which asks every author to know the rule.
affects:
  - /components/importer-records.md
  - /components/importer-documents.md
tested_by:
  - tests/test_records.py#test_plain_scalars_resolve_as_yaml_v3_resolves_them
  - tests/test_records.py#test_a_number_python_would_write_differently_is_refused
---

**Choice.** The loader keeps each scalar as text with its style, and `resolve` decides its value. Anam keeps a number's text, so a number that Python would write differently from Go is refused by name instead of changed, because another rendering would supersede the facet. The documents importer calls the same reader for sidecars.

**Why.** The text of a payload is part of a fact's content hash. A reader that resolves differently produces different facets from the same file.
