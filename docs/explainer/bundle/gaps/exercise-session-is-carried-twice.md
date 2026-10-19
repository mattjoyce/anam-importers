---
type: gap
title: The activity.exercise-session Definition is carried twice
description: The Garmin and Concept2 folders each hold a byte-identical copy of the activity.exercise-session Definition, and only a test, not the structure, keeps them equal.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - garmin/definitions/activity.exercise-session.json
  - concept2/definitions/activity.exercise-session.json
  - tests/test_concept2.py
---

A new version of the type means editing both files together. `test_the_definition_is_anam_s_and_the_garmin_importer_carries_the_same_one` fails if they differ. `ensure_published` also stops a run that carries a different body from the one Anam holds, so a drift would surface as a stopped run and not as bad data.
