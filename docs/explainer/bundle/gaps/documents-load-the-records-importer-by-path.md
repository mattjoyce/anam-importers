---
type: gap
title: The documents importer loads the records importer by file path
description: To share one YAML reader, documents/run.py imports records/run.py through importlib at module load, which couples two plugin folders that are otherwise independent.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - documents/run.py
  - records/run.py
---

The shared reader resolves scalars as Go yaml.v3 does, and both importers must agree on it. The cost is that `documents` cannot be deployed without the `records` folder beside it. Moving the reader into `anam_importer` would remove the coupling and would make it a base function.
