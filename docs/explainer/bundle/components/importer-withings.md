---
type: component
title: anam_withings
description: Reads a Withings plugin's SQLite database read-only and sends every measurement as health.measurement, with the group's attribution beside the value.
timestamp: 2026-10-17T00:00:00Z
resource: withings/run.py#batch_events
anchor: "def batch_events(request: Dict[str, Any], withings_id: Optional[int]) -> Dict[str, Any]:"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

Source `withings`, type `health.measurement` v4, identity `/withings_id` with `/type`, fact time `/date` in UTC. `handle` shapes the one measure group named by a `withings.measurement_recorded` event, or everything on `withings.reconciled`, since a reconcile can change old groups' attribution. `poll` shapes everything and labels the run a snapshot.

The SQL reads every column except `value` through `CAST(... AS TEXT)`, so the payload carries the source's own text. A REAL has no text of its own and SQLite's rendering varies by build, so `value` is read as a double and written by `render` as the shortest decimal that round-trips, never with an exponent. The database opens with `mode=ro`, and a database that is locked or busy is a retryable failure while a missing file or a missing `measure_groups` table is not. A group marked ambiguous (`attrib` equal to `"1"`) asserts no person. The only optional key is `busy_timeout_ms`.
