---
type: gap
title: The tests against a real daemon do not run in CI
description: The continuous-integration job runs the unit tests only, so the tests that prove a resend is a no-op against a real Anam skip there, as do the DreamStation and Garmin tests that need an external card, decoder or uv.
timestamp: 2026-10-17T00:00:00Z
looked_at:
  - .github/workflows/tests.yml
  - tests/test_against_anam.py
  - tests/test_dreamstation.py
  - tests/test_garmin.py
---

The workflow comments say so itself. A full local run reports 162 tests with 20 skipped when `ANAM_BIN` and a card copy are unset. The skipped ones include the cut-over and idempotency checks that most directly test the contract with Anam. A developer who changes shaping must run them locally with `ANAM_BIN` set. The Garmin tests also skip without `uv`, and the DreamStation importer needs Python 3.11 while the matrix runs 3.10 and 3.12.
