---
type: data-structure
title: Stay payload
description: The payload of a location.stay envelope, with an id, the device, the start and end, the centroid, the fix count, the spread in metres and an optional named place.
timestamp: 2026-10-17T00:00:00Z
resource: stays/run.py#payload
anchor: 'p: Dict[str, Any] = {"id": f"stay:{self.device}:{self.start}", "device": self.device,'
basis: code
tier: detail
group: sources
references:
  - to: /data-structures/spool-line.md
    how: derived from many
    card: "n:n"
---

`id` is `stay:<device>:<first fix instant>`. `lat` and `lon` are the centroid rounded to six places, `radius_m` the farthest fix from it to one place. `place` appears only when the geocoder named the cell and holds `name`, `geocoder`, `geocoded_at` and optional `display_name`, `osm_type`, `osm_id` and `address`. A payload over 290 KiB is skipped.
