---
type: component
title: anam_owntracks
description: Groups the location messages in an OwnTracks spool into one location.track facet per phone per UTC hour, sent whole every time the hour gains a message.
timestamp: 2026-10-17T00:00:00Z
resource: owntracks/run.py#read_spool
anchor: "def read_spool(root: Path) -> Read:"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

Source `owntracks`, type `location.track` v1, identity `/id` as `loc:<device>:<hour>`, fact time `/hour` in UTC. Messages are read in the receiver's id order, so the first message received for a fix wins. Two messages with one `tst` are one point, with their triggers merged. A second message at that time with a different latitude, longitude or accuracy is counted and dropped.

An hour's facet replaces the last one sent, so an hour is always sent whole, and `handle` sends the hours that gained a message received within `lookback_days`, and not only the new messages. Messages that are not locations, empty bodies and fields the Definition does not keep are counted in logs. A line that will not parse or an hour over `max_payload_bytes` is skipped and the run stops being a snapshot. Coordinates never appear in a log line, a result or an event name. See [coordinates stay in the payload](/invariants/coordinates-stay-in-the-payload.md).
