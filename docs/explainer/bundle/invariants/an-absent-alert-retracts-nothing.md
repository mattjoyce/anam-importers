---
type: invariant
title: An absent alert retracts nothing
description: When a complete resend leaves facets absent, anam_submit raises an alert with the counts and some ids, and retraction stays with an operator running a separate command.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/run.py#absent_event
anchor: "is retracted: the operator decides, with anam retract"
basis: code
tier: supporting
enforced_at: anam_submit/run.py#absent_event
enforced_anchor: "is retracted: the operator decides, with anam retract"
applies_to:
  - /components/anam-submit.md
tested_by:
  - tests/test_against_anam.py#test_a_complete_resend_reports_what_the_source_no_longer_holds
---

No importer or submit instance calls a retraction endpoint. A source that drops a fact is as likely to be a glitch as a deletion, so a person decides. The alert is keyed on the snapshot id, so a resent last part does not alert twice, and `absent_ids_shown` (default 20, at most 1000) bounds how many ids it carries.
