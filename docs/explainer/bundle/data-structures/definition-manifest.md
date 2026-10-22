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

Fourteen facet types ship in fourteen Definition files, one each. Every type is named `domain.concept[.specialisation]` under one of Anam's eight domains (card 147), a vendor's own payload shape at the vendor's leaf (anam cards 192 and 195), and each file declares `kind` and `family` in its `meta`, which the gate ignores and the inspector reads.

| Type | v | Folder | family, kind | Identity key | Fact time pointer, zone |
|---|---|---|---|---|---|
| `health.measurement.withings` | 2 | withings | body, reading | `/withings_id`, `/type` | `/date`, UTC |
| `health.blood-pressure` | 7 | bp_csv | vitals, reading | `/date_excel`, `/reading` | `/date_excel`, Australia/Sydney |
| `health.cpap-session.dreamstation` | 2 | dreamstation_card | sleep, event | `/device_serial`, `/session` | `/start`, UTC |
| `activity.day.garmin` | 1 | garmin | movement, measure | `/id` | interval start, Australia/Sydney |
| `activity.exercise-session.garmin` | 1 | garmin | exercise, event | `/id` | interval start, Australia/Sydney |
| `activity.steps` | 2 | garmin | movement, measure | `/id` | interval start, Australia/Sydney |
| `health.heart-rate-alert` | 5 | garmin | vitals, event | `/source`, `/kind`, `/fact_time` | `/fact_time`, UTC |
| `health.heart-rate.day` | 1 | garmin | vitals, measure | `/id` | interval start, Australia/Sydney |
| `health.heart-rate.hour` | 1 | garmin | vitals, measure | `/id` | interval start, UTC |
| `health.sleep-episode` | 2 | garmin | sleep, measure | `/id` | interval start, UTC |
| `activity.exercise-session.concept2` | 2 | concept2 | exercise, event | `/id` | interval start, Australia/Sydney |
| `place.track` | 2 | owntracks | location, measure | `/id` | `/hour`, UTC |
| `place.stay` | 2 | stays | location, event | `/id` | `/start`, UTC |
| `record.link` | 2 | links | documents, event | `/id` | `/date`, UTC |

All are `validation_mode: strict` with a closed schema. Seven of the types are copies of files Anam bundles, byte for byte: `health.blood-pressure`, `activity.exercise-session.garmin`, `activity.exercise-session.concept2`, `activity.steps`, `health.heart-rate-alert`, `health.heart-rate.day` and `health.sleep-episode`. The other seven belong to the importer that registers them. Their earlier versions stay under `<folder>/definitions/history/<type>.v<n>.json`, and the loader sends them with the current one, oldest first, so a rebuilt store holds every version the importer emitted (anam card 198); an old name's bodies stay there too and are not sent. Every type here carries `source_time`, the shape anam keeps in `internal/def/sourcetime/`, saying how its source's clock was read. A renamed type starts again at v1 under its new name, so the version column is not a count of how often the type has changed. `time_semantics.fact_time` holds the pointer, layout and zone, and `identity_key` lists the pointers. The Definitions that follow an external standard name it in `source_schema` (IEEE 1752 or Open mHealth), and `tests/conformance` pins those schemas. `health.heart-rate.day` follows none, since Open mHealth has no body for one day's several statistics, and names `anam/health.heart-rate.day`; so does `health.heart-rate.hour`, an hour's 60 minute slots, which names `anam/health.heart-rate.hour`. See [Facet Definition](/terms/facet-definition.md).
