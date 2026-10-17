---
type: invariant
title: A plugin always answers with exactly one response
description: Whatever a handler does, stdout holds one JSON object, with failures carrying a retry flag, because a traceback tells the supervisor nothing it can act on.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/ductile.py#run
anchor: "except Exception as exc:  # noqa: BLE001"
basis: code
tier: supporting
enforced_at: anam_importer/ductile.py#run
enforced_anchor: "except Exception as exc:  # noqa: BLE001"
applies_to:
  - /components/plugin-protocol.md
tested_by:
  - tests/test_base.py#test_an_unexpected_exception_is_still_a_protocol_response
  - tests/test_base.py#test_a_failure_carries_its_retry
---

The retry flag is how a source failure reaches the supervisor's retry policy. A locked database is retryable and a missing table is not. An unexpected exception is reported as not retryable, since retrying a bug only repeats it.
