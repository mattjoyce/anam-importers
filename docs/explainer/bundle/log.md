# Log

## 2026-10-17

First build of the bundle, at anam-importers commit 2b5dfd2b5ef330412d5d3dec1eb22b4e2c5917d4 (master, after card 168).

- The code did not change, because this is the baseline. The repository at this commit has the shared base and `anam_submit`, and nine importers (Withings, blood pressure CSV, DreamStation, records, documents, Garmin, Concept2, OwnTracks, stays) with the one-off extractors, the rebuild drill and the unit tests.
- The bundle holds one purpose, 17 terms, 21 components, 9 workflows, 14 data structures, 13 decisions, 15 invariants, 5 change paths and 7 gaps. Every resource, anchor, symbol and test named in the frontmatter is checked against the tracked files by `check.py`.
- Writing it turned up gaps to fix first. The stays importer does not range-check its config, the tests against a real daemon do not run in CI, and the README does not yet list stays.

## 2026-10-20, card 147

Anam-importers at a4d2155 (master, after the taxonomy merge). The purpose page's commit stays 2b5dfd2; `check.py` passes against the tracked files at a4d2155.

- Code: every importer names its types under the eight domains of anam card 147 (`health`, `activity`, `place`, `record`). A renamed type starts again at v1, and every Definition declares `kind` and `family`. Cards 165 (the links importer and `record.link`) and 174 (Garmin sleep instants in UTC) landed since the baseline.
- Bundle: the Definition manifest page lists all twelve types in thirteen files with their versions, `family` and `kind`, and says which six are byte copies of Anam's bundled files. The bp-csv, Withings and Concept2 pages name the versions now in force (`health.blood-pressure` v6, `health.measurement` v4, `activity.exercise-session` v1). Counts: 1 purpose, 17 terms, 22 components, 10 workflows, 14 data structures, 13 decisions, 15 invariants, 5 change paths and 7 gaps.

## 2026-10-21, anam card 195

- Code: vendor-shaped types take the vendor leaf. Garmin sends `activity.exercise-session.garmin` and `activity.day.garmin`, Concept2 `activity.exercise-session.concept2`, Withings `health.measurement.withings` and DreamStation `health.cpap-session.dreamstation`; the Technogym and Strong extractors write `activity.exercise-session.technogym` and `.strong`. The two exercise leaves here are byte copies of the bodies Anam bundles; the three registered leaves are their old type's body under the new name, the old body kept in `definitions/history/`. `activity.day.garmin` reads its fact time at the start of the day Garmin counted. `retype_records.py` takes a rename table's select rows.
- Bundle: the Definition manifest page lists thirteen types in thirteen files with the versions in force; the Garmin, Concept2, Withings and DreamStation pages name the leaves. The gap "activity.exercise-session is carried twice" is closed, since each importer now carries its own leaf. The snapshot invariant's anchor follows `garmin/run.py`. Counts: 1 purpose, 17 terms, 22 components, 10 workflows, 14 data structures, 13 decisions, 15 invariants, 5 change paths and 6 gaps.

## 2026-10-21, anam card 198

- Code: every importer says how its clock was read. `source_time` (value, zone, basis) is sent by bp_csv (`date_excel`, its new `zone` key or an assumption), withings (`date`, UTC), concept2 (`date_utc`, UTC; a web entry's date in the Logbook's `timezone` or an assumed Sydney), documents (the sidecar's date, an assumed Sydney), links (by `date_from`), dreamstation, owntracks and stays (UTC epochs), and the extractors `fitbit_sleep.py`, `strong_csv.py`, `technogym_json.py` and `acl_pathology.py`. Wall clocks are read by `clock.local_instant`, so one a zone skips or repeats is left out, never guessed. `load` reads `definitions/history/<type>.v<n>.json` for the types an importer emits now and every batch carries every version, oldest first. New versions: `health.measurement.withings`, `health.cpap-session.dreamstation`, `place.track`, `place.stay` and `record.link` v2 here; `health.blood-pressure` v7 and `activity.exercise-session.concept2` v2 are Anam's bodies, byte for byte.
- Bundle: the Definition manifest page names the versions and the history rule; the importer-definitions decision says every version is sent; the bp_csv, Concept2, Withings, DreamStation, OwnTracks, stays, links and documents pages say how each reads its clock; two workflow anchors follow the code.

## 2026-10-22, anam card 205

- Code: Garmin sends one `health.heart-rate.day` a day, its resting, minimum and maximum as fields, in place of three `health.heart-rate-day` facts. The new Definition is Anam's, bundled, and the copy in `garmin/definitions/` is byte for byte; the old copy is gone. `poll`'s snapshot names `RETIRED_TYPES` with none carried, so the old facts are reported absent and `anam retract garmin` tombstones them, which `tests/test_garmin.py` proves against a real daemon.
- Bundle: the Definition manifest page and the Garmin page name `health.heart-rate.day` v1, and the ids decision says why its bare-day id collides with nothing.

## 2026-10-22, anam card 129

- Code: Garmin sends an hour's heart rate, `health.heart-rate.hour` (a new Definition, the importer's own), read from the monitoring FIT files beside the alert. Each UTC hour with a sample is one facet of 60 slots, slot *i* minute *i*, the watch's reading in that minute or `null` for a minute with none; an hour with no sample is no facet, a minute sampled twice keeps the last sample, and nothing is averaged or bucketed. A monitoring message's 16-bit short timestamp is resolved against the last full one in its file, and a sample that cannot be placed is logged and makes the run no snapshot. Reading the file rather than GarminDB's `monitoring_hr` keeps the samples that table drops and the UTC instants it rewrites as local wall clock.
- Bundle: the Definition manifest page lists fourteen types in fourteen files; the Garmin page and the ids decision name the hour, whose id is the bare RFC 3339 instant because no other type of this source keys on one. Page counts are unchanged.
