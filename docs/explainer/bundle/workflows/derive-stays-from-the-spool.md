---
type: workflow
title: Derive stays from the spool
description: The stays importer reads the OwnTracks spool, finds runs of fixes that held within a radius, names each centroid through a cached geocoder, and emits place.stay envelopes.
timestamp: 2026-10-17T00:00:00Z
resource: stays/run.py#run_over
anchor: "whole = read.bad == 0 and len(payloads) == len(stays)"
basis: code
tier: supporting
trigger: A pipeline runs anam_stays handle after the spool is pulled, or a person runs poll.
steps:
  - actor: /components/importer-stays.md
    caller: /components/ductile-gateway.md
    label: read the spool in id order
    action: "Every `*/*.jsonl` file under `spool_dir`. A last line without its newline is not read yet. A line that is not a spool line is counted as bad, without its content."
    reads: [/data-structures/spool-line.md]
    resource: stays/run.py#read_spool
    anchor: 'for path in sorted(p for p in root.glob("*/*.jsonl") if p.is_file()):'
  - actor: /components/importer-stays.md
    label: keep the first fix for each time
    action: "Only location messages with a positive `tst` and in-range coordinates count. A repeated fix time keeps the first message received."
    resource: stays/run.py#read_spool
    anchor: "by_tst.setdefault(tst, Fix(device, tst, float(lat), float(lon),"
  - actor: /components/importer-stays.md
    label: find runs that held within the radius
    action: "From an anchor fix, extend while fixes stay within `radius_m` of it. If the run spans at least `min_dwell_minutes` it is a stay. Fixes between stays are movement and make nothing."
    resource: stays/run.py#detect_stays
    anchor: "if members[-1].tst - members[0].tst >= min_dwell_s:"
  - actor: /components/importer-stays.md
    label: build the geocoder and its cache
    action: "`geocache_dir` is required. The endpoint, the contact User-Agent and the minimum gap between calls are keys with defaults."
    resource: stays/run.py#build_geocoder
    anchor: 'cache = Cache(Path(str(config["geocache_dir"])))'
  - actor: /components/geocoder.md
    caller: /components/importer-stays.md
    label: name the centroid, from cache or once
    action: "A cached cell returns its answer with the time it was fetched. Otherwise one rate-limited call is made. A failed call returns nothing and the stay goes without a place."
    resource: stays/geocode.py#geocoder
    anchor: "cached = cache.get(lat, lon)"
  - actor: /components/importer-stays.md
    label: build the stay payload
    action: "The centroid is the mean of the fixes, rounded to six places. `place` is added only when the geocoder produced a name."
    writes: [/data-structures/stay-payload.md]
    resource: stays/run.py#payload
    anchor: 'place = place_from(entry["data"], entry["at"])'
  - actor: /components/importer-stays.md
    label: validate, batch, judge the snapshot
    action: "A payload over 290 KiB is logged and skipped, and a bad spool line leaves fixes out, so either stops the run being a snapshot. Only `poll` can label a snapshot. The events go to `anam_submit` as in [submit a batch](/workflows/submit-a-batch.md)."
    writes: [/data-structures/envelope.md, /data-structures/batch-event.md]
    ends: true
    resource: stays/run.py#run_over
    anchor: "whole = read.bad == 0 and len(payloads) == len(stays)"
---

The raw fix stays raw in `place.track`, and the stay is a separate derived facet. A geocoder that is down cannot block a stay, because the place is an enrichment that backfills when a later run succeeds. The same stay id is sent again with a `place` and supersedes the placeless one.
