---
type: data-structure
title: Definition manifest
description: A JSON file with a meta block and a closed JSON Schema, in the format Anam publishes and an importer carries, one file per facet type.
timestamp: 2026-10-17T00:00:00Z
resource: stays/definitions/location.stay.json#identity_key
anchor: '"identity_key": ['
basis: code
tier: supporting
group: contract
references: []
---

Eleven facet types ship across twelve Definition files, since `exercise.session` is carried twice.

| Type | v | Folder | Identity key | Fact time pointer, zone |
|---|---|---|---|---|
| `health.measurement` | 3 | withings | `/withings_id`, `/type` | `/date`, UTC |
| `health.blood-pressure` | 5 | bp_csv | `/date_excel`, `/reading` | `/date_excel`, Australia/Sydney |
| `sleep.cpap-session` | 1 | dreamstation_card | `/device_serial`, `/session` | `/start`, UTC |
| `exercise.session` | 5 | garmin, concept2 | `/id` | interval start, Australia/Sydney |
| `sleep.episode` | 1 | garmin | `/id` | interval start, UTC |
| `health.heart-rate-daily` | 1 | garmin | `/id`, `/statistic` | interval start, Australia/Sydney |
| `health.step-count` | 1 | garmin | `/id` | interval start, Australia/Sydney |
| `garmin.day` | 1 | garmin | `/id` | `/day`, Australia/Sydney |
| `health.heart-rate-alert` | 3 | garmin | `/source`, `/kind`, `/fact_time` | `/fact_time`, UTC |
| `location.track` | 1 | owntracks | `/id` | `/hour`, UTC |
| `location.stay` | 1 | stays | `/id` | `/start`, UTC |

All are `validation_mode: strict` with a closed schema. Garmin and Concept2 carry byte-identical copies of `exercise.session`. `time_semantics.fact_time` holds the pointer, layout and zone, and `identity_key` lists the pointers. The Definitions that follow an external standard name it in `source_schema` (IEEE 1752 or Open mHealth), and `tests/conformance` pins those schemas. See [Facet Definition](/terms/facet-definition.md).
