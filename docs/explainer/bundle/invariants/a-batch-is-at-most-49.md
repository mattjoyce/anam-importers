---
type: invariant
title: A batch is at most 49 envelopes
description: No submission carries more than 49 envelopes, and a larger one is cut, because Anam refuses it and the number decides which events share a commit.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#MAX_BATCH
anchor: "MAX_BATCH = 49"
basis: code
tier: core
enforced_at: anam_importer/envelopes.py#batches
enforced_anchor: "raise ValueError(f\"batch size {size} is outside 1..{MAX_BATCH}\")"
applies_to:
  - /components/envelopes.md
  - /components/anam-submit.md
tested_by:
  - tests/test_base.py#test_batches_hold_at_most_49
  - tests/test_base.py#test_a_batch_size_past_the_gate_is_refused
---

The constant is commented "Not configurable" because both ends must agree. Every importer cuts through `batches`, and the `anam_submit` manifest repeats the bound as `maxItems: 49`. A smaller batch only means more transactions.
