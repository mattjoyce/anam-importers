---
type: data-structure
title: Spool line
description: One JSON line of the OwnTracks spool, holding the receiver's id, the phone's message body as text, and when it was received.
timestamp: 2026-10-17T00:00:00Z
resource: stays/run.py#read_spool
anchor: 'if not isinstance(row, dict) or not isinstance(row.get("id"), int) or not isinstance(row.get("body"), str):'
basis: code
tier: detail
group: sources
references: []
---

`{id, body, received_at}`. `id` orders messages and decides which of two messages for one fix is first. `body` is a string holding JSON, a location message with `_type` equal to `location`, `tst` (epoch seconds), `lat` and `lon`, and optional `acc`, `alt`, `vel`, `batt` and others. `received_at` is epoch seconds and is what `lookback_days` compares against, because a phone that was offline sends old fixes late.
