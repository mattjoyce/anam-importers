---
type: invariant
title: An envelope names no source and no source reference
description: The token names the source and Anam composes identity from the Definition, so an importer's envelope carries a type, a version, a payload and at most an asserted person.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#envelope
anchor: "It names no source and no"
basis: code
tier: supporting
enforced_at: anam_importer/envelopes.py#envelope
enforced_anchor: "It names no source and no"
applies_to:
  - /components/envelopes.md
  - /components/importer-records.md
  - /components/importer-documents.md
tested_by:
  - tests/test_base.py#test_an_envelope_names_no_source
---

The base function builds only the four keys. The records and documents importers build their own dictionaries, and the same rule holds there by review, not by a shared function. The rule decides who can lie about provenance, and the answer is nobody but the token.
