---
type: decision
title: A track hour is sent whole every time it changes
description: The OwnTracks importer makes one facet per phone per UTC hour holding all its points, and re-sends the whole hour when any point arrives, because the new facet version replaces the last.
timestamp: 2026-10-17T00:00:00Z
resource: owntracks/run.py#run_over
anchor: "hours = [h for h in hours if h.received >= since]"
basis: code
tier: detail
alternatives:
  - One facet per fix, which makes a day of tracking thousands of facets and gives each late message its own.
  - Send only the new points of an hour, which a replacing facet would turn into a truncated hour.
affects:
  - /components/importer-owntracks.md
  - /terms/lookback-window.md
tested_by:
  - tests/test_owntracks.py#test_handle_sends_whole_hours_that_gained_a_message
---

**Choice.** `handle` reads the whole spool and sends the hours that gained a message received within `lookback_days`. Late-arriving messages count by receipt time, so a phone that was offline for a day still updates the right hours.

**What it costs.** An hour's payload grows with its points, and one over `max_payload_bytes` (default 290 KiB, set below Anam's payload bound) is skipped with a log line and breaks the snapshot.
