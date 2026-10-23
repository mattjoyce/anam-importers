---
type: component
title: anam_garmin
description: Shapes what a Garmin watch recorded into seven types, from GarminDB's SQLite file and the watch's FIT files, keeping no state of its own.
timestamp: 2026-10-22T00:00:00Z
resource: garmin/run.py#run_over
anchor: "def run_over(config: Dict[str, Any], s: Settings, monitoring: List[Path], activities: List[Path],"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

Source `garmin`. It reads GarminDB's `garmin.db` read-only (sleep, daily heart rate, daily summary) and FIT files decoded with Garmin's FIT SDK (pinned in the script header).

| Type | Version | From | Identity |
|---|---|---|---|
| `health.heart-rate-alert` | 5 | monitoring FIT event number 66 | source, kind, fact_time |
| `health.heart-rate.hour` | 1 | monitoring FIT heart rate messages | `/id`, the UTC hour |
| `activity.exercise-session.garmin` | 1 | activity FIT session messages | `/id`, `garmin:session:<UTC start>` |
| `health.sleep-episode` | 2 | `sleep` table | `/id`, `sleep:<day>` |
| `health.heart-rate.day` | 1 | `resting_hr` and `daily_summary` | `/id`, the bare day |
| `activity.steps` | 2 | `daily_summary` | `/id`, `steps:<day>` |
| `activity.day.garmin` | 1 | the rest of `daily_summary` | `/id`, `day:<day>` |

An alert's heart rate is the high byte of the event's 16-bit data and the watch's threshold the low byte. The session start comes from the FIT file as a true UTC instant, because the database holds wall clock. Sport and sub-sport map to Google Fit names through `ACTIVITY_NAMES`, and an unmapped pair is `unknown` while the raw FIT names stay in the payload. A FIT file that will not decode is logged and skipped, and the run then is not a snapshot. `handle` reads files modified within `lookback_days`; `poll` reads all. A day's resting, minimum and maximum heart rate are one `health.heart-rate.day` (anam card 205), and a figure Garmin left empty is no field. The same monitoring files' heart rate is also read an hour at a time (anam card 129): `health.heart-rate.hour` is 60 slots, slot *i* minute *i*, each the watch's reading in that minute or null for one it recorded none, so an hour with no sample is no facet and nothing is averaged. A FIT timestamp is UTC by the format's definition, so the hours are UTC's; a message's 16-bit short timestamp is placed by the last full one in its file, and a sample with no instant to place it by is logged and makes the run no snapshot. `poll`'s snapshot also names the types in `RETIRED_TYPES` with none carried, so Anam reports their facts absent and `anam retract garmin` tombstones them; a type comes off the list once that has run. The list is empty now, after `health.heart-rate-day`, the three facts a day it sent before card 205, was retracted (anam card 208). See [ids name what they are](/decisions/ids-name-what-they-are.md).
