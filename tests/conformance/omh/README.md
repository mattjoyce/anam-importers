# Open mHealth schemas, pinned

Copied unchanged from github.com/openmhealth/schemas, `schema/omh/`, at commit df386000a93a
(branch `main`), the schemas `heart-rate-2.0.json` reaches. Open mHealth's `$ref`s name a
minor-version range (`unit-value-1.x.json`); each file here is kept under the name its `$ref`
uses, holding the newest 1.y at that commit:

| Name here | Copied from |
|---|---|
| `date-time-1.x.json` | `date-time-1.0.json` |
| `descriptive-statistic-1.x.json` | `descriptive-statistic-1.2.json` |
| `duration-unit-value-1.x.json` | `duration-unit-value-1.0.json` |
| `part-of-day-1.x.json` | `part-of-day-1.0.json` |
| `temporal-relationship-to-physical-activity-1.x.json` | `temporal-relationship-to-physical-activity-1.0.json` |
| `temporal-relationship-to-sleep-1.x.json` | `temporal-relationship-to-sleep-1.0.json` |
| `time-frame-1.x.json` | `time-frame-1.0.json` |
| `time-interval-1.x.json` | `time-interval-1.0.json` |
| `unit-value-1.x.json` | `unit-value-1.0.json` |

`tests/test_conformance.py` holds the payloads of each Definition whose `source_schema` is
`omh/<name>` to the pinned schema.
