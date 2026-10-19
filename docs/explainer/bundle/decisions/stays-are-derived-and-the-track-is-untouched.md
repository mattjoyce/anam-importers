---
type: decision
title: Stays are derived, and the track is untouched
description: Naming the places a phone stopped is a separate importer and a separate facet type, so place.track facets keep the raw fixes and a geocoder outage never blocks them.
timestamp: 2026-10-17T00:00:00Z
resource: stays/run.py#detect_stays
anchor: "Fixes between stays are movement and make no stay."
basis: code
tier: detail
alternatives:
  - Add a place name to each place.track hour, which changes a raw fact with a derived guess and re-sends every hour when a geocoder improves.
  - Compute stays in a read over the track, which gives the place no home as a fact with its own time.
affects:
  - /components/importer-stays.md
  - /components/importer-owntracks.md
  - /components/geocoder.md
tested_by:
  - tests/test_stays.py#test_handle_emits_a_conforming_placeless_stay
---

**Choice.** The stays importer reads the same spool as the OwnTracks importer and sends `place.stay` under its own source. The detection thresholds and the geocoder are config keys with defaults.

**Why.** A fix is a measurement and a stay is an interpretation. Keeping them apart means a better threshold or geocoder rewrites only stays. The place is an enrichment, so it can be absent and backfill later.
