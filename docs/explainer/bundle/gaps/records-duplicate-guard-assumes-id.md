---
type: gap
title: The records duplicate guard assumes id for every type but one
description: The local duplicate check uses a record's id as its identity unless the type is health.blood-pressure, so a bundled type whose Definition keys identity on other fields could slip a duplicate past it.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - records/run.py
---

`IDENTITY` has one entry, and its comment says it restates Anam's bundled Definition because the importer neither carries nor fetches Definitions. I could not confirm from this repository which other bundled types key on something other than `id`. The gate still composes the true identity and keeps the last payload sent, so the cost of a miss is a silent supersession within a run and not a corrupt record.
