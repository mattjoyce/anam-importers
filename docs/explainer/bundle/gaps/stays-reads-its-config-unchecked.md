---
type: gap
title: The stays importer reads its config unchecked
description: Every other importer range-checks its keys through the config helpers, but stays converts them with float() and str(), is not in the config test, and is absent from the README table and the defaults list.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - stays/run.py
  - tests/test_config.py
  - README.md
  - docs/defaults-and-invariants.md
---

`build_geocoder`, `all_stays` and `handle` read `radius_m`, `min_dwell_minutes`, `rate_limit_seconds`, `lookback_days` and the endpoint and User-Agent straight from the config with `float(config.get(...))`. A non-numeric value raises a `ValueError` that the protocol reports as not retryable, but it does not name the key, and a zero or negative value is not refused. `AGENTS.md` says each command reads its keys first through `anam_importer.config`. The README's list of importers and `docs/defaults-and-invariants.md` also do not mention `anam_stays` yet, although it is on master with a manifest, a Definition and 13 tests. The fix is a `Settings` tuple in the shape Garmin and OwnTracks use, a case in `PluginsTest`, and rows in the two documents.
