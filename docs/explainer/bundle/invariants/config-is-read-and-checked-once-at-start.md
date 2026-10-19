---
type: invariant
title: Config is read and checked once, at the start of a command
description: Each command reads its keys through the config helpers into values it passes down, and a bad value fails there naming the key before any source or Anam is touched.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/config.py#bad
anchor: 'return Failure(f"config {key}: {why}", retry=False)'
basis: code
tier: supporting
enforced_at: anam_importer/config.py#bad
enforced_anchor: 'return Failure(f"config {key}: {why}", retry=False)'
applies_to:
  - /components/config-helpers.md
  - /components/importer-garmin.md
  - /components/importer-concept2.md
  - /components/importer-owntracks.md
  - /components/importer-withings.md
  - /components/importer-links.md
tested_by:
  - tests/test_config.py#test_every_plugin_refuses_a_bad_value_at_start
---

The test passes source paths that do not exist and bad keys, then asserts the error names the key, which shows the check ran first. The stays importer is not yet covered, see [stays reads its config unchecked](/gaps/stays-reads-its-config-unchecked.md).
