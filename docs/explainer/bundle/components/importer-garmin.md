---
type: component
title: anam_garmin
description: Shapes what a Garmin watch recorded into six types, from GarminDB's SQLite file and the watch's FIT files, keeping no state of its own.
timestamp: 2026-10-17T00:00:00Z
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
| `activity.exercise-session.garmin` | 1 | activity FIT session messages | `/id`, `garmin:session:<UTC start>` |
| `health.sleep-episode` | 2 | `sleep` table | `/id`, `sleep:<day>` |
| `health.heart-rate-day` | 2 | `resting_hr` and `daily_summary` | `/id` with `/statistic` |
| `activity.steps` | 2 | `daily_summary` | `/id`, `steps:<day>` |
| `activity.day.garmin` | 1 | the rest of `daily_summary` | `/id`, `day:<day>` |

An alert's heart rate is the high byte of the event's 16-bit data and the watch's threshold the low byte. The session start comes from the FIT file as a true UTC instant, because the database holds wall clock. Sport and sub-sport map to Google Fit names through `ACTIVITY_NAMES`, and an unmapped pair is `unknown` while the raw FIT names stay in the payload. A FIT file that will not decode is logged and skipped, and the run then is not a snapshot. `handle` reads files modified within `lookback_days`; `poll` reads all. See [ids name what they are](/decisions/ids-name-what-they-are.md).
