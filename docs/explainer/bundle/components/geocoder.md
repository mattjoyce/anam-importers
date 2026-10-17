---
type: component
title: Geocoder (stays.geocode)
description: A rate-limited Nominatim reverse-geocoding client with an on-disk cache keyed by grid cell, which returns nothing rather than raising when the service is unreachable.
timestamp: 2026-10-17T00:00:00Z
resource: stays/geocode.py#geocoder
anchor: "def geocoder(nominatim: Nominatim, cache: Cache)"
basis: code
tier: detail
group: importers
depends_on: []
---

`Nominatim.reverse` waits out `rate_limit_seconds` between calls, sends a contact User-Agent in place of a token, and returns the answer only for a 200 with an `address`. It catches network and parse errors and returns None, and it bounds the answer at 1 MiB. `Cache` stores answers as JSON files named for the centroid rounded to four decimal places (`CELL_DP`, about 11 metres), so a stay re-sent as it grows and a second stay at the same spot make no new call.

A named cell is cached with the time it was fetched, so `geocoded_at` stays honest across re-sends. An unnamed cell is not cached and is tried again next run. `name_from` picks a readable name from address keys by rank (locality, city, state, country) and falls back to the display name. See [the geocoder is outside the error kernel](/invariants/a-down-geocoder-never-stops-a-stay.md).
