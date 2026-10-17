---
type: invariant
title: Every payload is validated before anything leaves
description: An importer runs check on all its envelopes against the Definitions it carries before emitting an event, so a later refusal means the two sides disagree and not that a row was malformed.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#check
anchor: "def check(definitions: Dict[str, Definition], envelopes: Iterable[Dict[str, Any]]) -> None:"
basis: code
tier: supporting
enforced_at: anam_importer/envelopes.py#check
enforced_anchor: "raise Invalid(problems)"
applies_to:
  - /components/envelopes.md
  - /components/importer-withings.md
  - /components/importer-bp-csv.md
  - /components/importer-garmin.md
  - /components/importer-owntracks.md
tested_by:
  - tests/test_base.py#test_check_refuses_with_every_problem
---

`check` collects every problem across all envelopes and raises `Invalid` once. A whole run therefore fails before any batch event exists. The records and documents importers carry no Definition and do not call it. The gate is their validator.
