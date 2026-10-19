---
type: component
title: anam_stays
description: Derives place.stay facets from the same spool by finding runs of fixes that held within a radius, and names each stay's centroid once through a cached geocoder.
timestamp: 2026-10-17T00:00:00Z
resource: stays/run.py#detect_stays
anchor: "def detect_stays(fixes: List[Fix], radius_m: float, min_dwell_s: float) -> List[Stay]:"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/plugin-protocol.md
  - /components/geocoder.md
---

Source `stays`, type `place.stay` v1, identity `/id` as `stay:<device>:<start>`, fact time `/start` in UTC. A stay is a maximal run of fixes that began at an anchor and stayed within `radius_m` (default 100) of it for at least `min_dwell_minutes` (default 10). The payload holds the centroid rounded to six places, the start and end, the fix count, the spread, and a `place` when the geocoder named it.

The `place.track` facets are never changed, so the raw fix stays raw. A stay is derived from the spool, and a stay that is still growing is re-sent whole under the same id and supersedes itself. `handle` sends stays whose last fix was received within `lookback_days`. See [derive stays, do not change the track](/decisions/stays-are-derived-and-the-track-is-untouched.md).
