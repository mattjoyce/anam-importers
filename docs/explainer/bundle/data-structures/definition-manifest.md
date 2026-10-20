---
type: data-structure
title: Definition manifest
description: A JSON file with a meta block and a closed JSON Schema, in the format Anam publishes and an importer carries, one file per facet type.
timestamp: 2026-10-17T00:00:00Z
resource: stays/definitions/place.stay.json#identity_key
anchor: '"identity_key": ['
basis: code
tier: supporting
group: contract
references: []
---

Twelve facet types ship across thirteen Definition files, since `activity.exercise-session` is carried twice. Every type is named `domain.concept` under one of Anam's eight domains (card 147), and each file declares `kind` and `family` in its `meta`, which the gate ignores and the inspector reads.

| Type | v | Folder | family, kind | Identity key | Fact time pointer, zone |
|---|---|---|---|---|---|
| `health.measurement` | 4 | withings | body, reading | `/withings_id`, `/type` | `/date`, UTC |
| `health.blood-pressure` | 6 | bp_csv | vitals, reading | `/date_excel`, `/reading` | `/date_excel`, Australia/Sydney |
| `health.cpap-session` | 1 | dreamstation_card | sleep, event | `/device_serial`, `/session` | `/start`, UTC |
| `activity.exercise-session` | 1 | garmin, concept2 | exercise, event | `/id` | interval start, Australia/Sydney |
| `health.sleep-episode` | 1 | garmin | sleep, measure | `/id` | interval start, UTC |
| `health.heart-rate-day` | 1 | garmin | vitals, measure | `/id`, `/statistic` | interval start, Australia/Sydney |
| `activity.steps` | 1 | garmin | movement, measure | `/id` | interval start, Australia/Sydney |
| `activity.day` | 1 | garmin | movement, measure | `/id` | `/day`, Australia/Sydney |
| `health.heart-rate-alert` | 4 | garmin | vitals, event | `/source`, `/kind`, `/fact_time` | `/fact_time`, UTC |
| `place.track` | 1 | owntracks | location, measure | `/id` | `/hour`, UTC |
| `place.stay` | 1 | stays | location, event | `/id` | `/start`, UTC |
| `record.link` | 1 | links | documents, event | `/id` | `/date`, UTC |

All are `validation_mode: strict` with a closed schema. Six of the types are copies of files Anam bundles, byte for byte: `health.blood-pressure`, `activity.exercise-session` (in both folders), `activity.steps`, `health.heart-rate-alert`, `health.heart-rate-day` and `health.sleep-episode`. The other six belong to the importer that registers them. A renamed type starts again at v1 under its new name, so the version column is not a count of how often the type has changed. `time_semantics.fact_time` holds the pointer, layout and zone, and `identity_key` lists the pointers. The Definitions that follow an external standard name it in `source_schema` (IEEE 1752 or Open mHealth), and `tests/conformance` pins those schemas. See [Facet Definition](/terms/facet-definition.md).
