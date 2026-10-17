---
type: decision
title: The client trusts only a whole receipt
description: A 200 from Anam counts as success only when its body is a complete admission receipt, and anything less is a retryable error that emits no admitted event.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/client.py#admission
anchor: "Anything less is not"
basis: code
tier: supporting
alternatives:
  - Treat any 200 as success, which would let a proxy page, a wrong endpoint or a truncated body look like an admitted batch.
  - Retry only on non-2xx statuses, which cannot recover a damaged 200.
affects:
  - /components/anam-client.md
  - /components/anam-submit.md
  - /data-structures/admission-receipt.md
tested_by:
  - tests/test_client.py#test_a_200_that_is_not_a_receipt_is_a_retryable_error_with_no_admitted_event
---

**Choice.** `admission` checks the shape of the receipt against the number of envelopes sent. `_malformed` makes the error retryable, because a later try may reach Anam.

**Why.** Success here moves a snapshot toward completion and tells an operator that data is in the record. A response that merely says 200 is not evidence of either. Resending is cheap and safe, because a batch that did land comes back all no-op.

**What it costs.** An Anam that changes the receipt's shape will make every submit fail loudly until the client follows. That is the intended direction of the failure.
