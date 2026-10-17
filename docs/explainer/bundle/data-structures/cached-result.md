---
type: data-structure
title: Cached Logbook result
description: One JSON file per workout under cache_dir, holding the Logbook's result object and its strokes exactly as fetched.
timestamp: 2026-10-17T00:00:00Z
resource: concept2/run.py#write_cached
anchor: 'tmp.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True))'
basis: code
tier: detail
group: sources
references: []
---

`{result, strokes}` in `<result id>.json`. `fetch` writes it when the result is new, when the listing's result differs from the cached one, or when strokes are expected and missing, and deletes files for ids the Logbook no longer lists. Shaping reads only this folder. A file that is not a cached result is logged and skipped, which also stops that run being a snapshot.
