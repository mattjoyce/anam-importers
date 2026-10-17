---
type: data-structure
title: Admission receipt
description: Anam's 200 answer to a batch, with the new watermark, the change count and one outcome per envelope, which the client accepts only when every part is present and consistent.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/client.py#admission
anchor: "def admission(body: Any, sent: int) -> Dict[str, Any]:"
basis: code
tier: supporting
group: wire
references: []
---

`{w, changed, results[{index, outcome}], snapshot?}`. `w` is a positive integer, `results` has exactly one entry per envelope sent with a distinct index in range and an outcome from `OUTCOMES`, and `changed` equals the number of `admitted` plus `superseded`. When the batch was labelled and its part completed the snapshot, the receipt's `snapshot.complete` is true and `anam_submit` asks for the report. A 422 is different, a `refused` list naming every envelope and the reason, and it raises `Refused`.
