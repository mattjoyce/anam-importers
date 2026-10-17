---
type: invariant
title: Every external call has one total deadline and a size cap
description: A call to Anam or the Logbook is bounded across connect, headers and body, and an answer over the cap is an error, so a plugin never hangs and never reads without limit.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/client.py#Client
anchor: "no answer within"
basis: code
tier: supporting
enforced_at: anam_importer/client.py#Client
enforced_anchor: "deadline = time.monotonic() + self.timeout"
applies_to:
  - /components/anam-client.md
  - /components/importer-concept2.md
  - /components/geocoder.md
tested_by:
  - tests/test_client.py#test_the_timeout_is_a_total_deadline
  - tests/test_client.py#test_an_oversized_answer_is_refused
---

The defaults are 30 seconds and 8 MiB, both keys. The client also sends the deadline to the daemon in an `Anam-Timeout` header in whole milliseconds, at least 1. The geocoder uses a fixed 10 second timeout and a 1 MiB cap and returns nothing on failure.
