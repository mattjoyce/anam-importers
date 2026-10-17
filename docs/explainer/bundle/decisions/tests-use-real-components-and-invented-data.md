---
type: decision
title: Tests use real components and invented data
description: Tests run plugins as subprocesses on real SQLite files and real folders, run against a real anam daemon when ANAM_BIN is set, and use only made-up values.
timestamp: 2026-10-17T00:00:00Z
resource: tests/helpers.py#run_plugin
anchor: "One ductile invocation"
basis: code
tier: supporting
alternatives:
  - Mock the Anam client and the sources, which tests the importer against its own assumptions.
  - Test only against recorded real exports, which cannot be published and ties the tests to one person.
affects:
  - /components/test-harness.md
  - /workflows/check-an-importer-against-a-real-daemon.md
tested_by:
  - tests/test_conformance.py#test_the_pinned_schema_is_not_a_pass_for_anything
---

**Choice.** `withings_db` builds a database in the shape the source plugin writes. Other tests write CSV, YAML, spool lines, FIT-shaped fixtures and Logbook responses from a small fake server. Conformance tests validate payloads against pinned copies of the IEEE 1752 and Open mHealth schemas under `tests/conformance`.

**What is synthetic.** All of it. Names, ids, serials, readings, coordinates and tokens are invented, or generated per run. The DreamStation card tests need a real card copy (`DREAMSTATION_CARD`) and the decoder, and skip without both. No test needs a network.
