# Log

## 2026-10-17

First build of the bundle, at anam-importers commit 2b5dfd2b5ef330412d5d3dec1eb22b4e2c5917d4 (master, after card 168).

- The code did not change, because this is the baseline. The repository at this commit has the shared base and `anam_submit`, and nine importers (Withings, blood pressure CSV, DreamStation, records, documents, Garmin, Concept2, OwnTracks, stays) with the one-off extractors, the rebuild drill and the unit tests.
- The bundle holds one purpose, 17 terms, 21 components, 9 workflows, 14 data structures, 13 decisions, 15 invariants, 5 change paths and 7 gaps. Every resource, anchor, symbol and test named in the frontmatter is checked against the tracked files by `check.py`.
- Writing it turned up gaps to fix first. The stays importer does not range-check its config, the tests against a real daemon do not run in CI, and the README does not yet list stays.
