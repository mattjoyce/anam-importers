---
type: invariant
title: An importer reads its source and does not write to it
description: SQLite sources open read-only, files and folders are read and not modified, and the only files an importer writes are its own cache and geocoder cache.
timestamp: 2026-10-17T00:00:00Z
resource: withings/run.py#open_source
anchor: 'sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=busy_ms / 1000)'
basis: code
tier: detail
enforced_at: withings/run.py#open_source
enforced_anchor: "?mode=ro"
applies_to:
  - /components/importer-withings.md
  - /components/importer-garmin.md
  - /components/importer-bp-csv.md
  - /components/importer-documents.md
  - /components/importer-links.md
---

Garmin opens `garmin.db` with `mode=ro` too. The Concept2 cache and the stays geocoder cache are the importer's own, written atomically or tolerating failure. The links importer's `state_file` is required and refused under `links_dir`. Most importer manifests say the plugin "holds no token and writes nothing".
