---
type: gap
title: Where shaping ends and identity begins is not fully settled
description: The rule says an importer composes no identity, but importers write the payload fields the identity key points at, and the records importer composes identity locally to refuse duplicates.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - AGENTS.md
  - bp_csv/run.py
  - garmin/run.py
  - records/run.py
---

Anam composes identity from `identity_key`, so no importer builds a source reference. But the blood pressure importer invents an ordinal `reading` that is half the identity, Garmin writes `id` strings such as `sleep:<day>`, and the records importer passes a record's own `id` through as text. `records/run.py` also restates the blood pressure key in `IDENTITY` and uses `id` for every other type, to refuse two records that claim one identity in a run. I read this as shaping, because the fields exist in the payload and Anam decides what they mean, but the wording of the rule does not settle it.
