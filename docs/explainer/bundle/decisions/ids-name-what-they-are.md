---
type: decision
title: Payload ids name what they are
description: The Garmin importer prefixes its ids (garmin:session:, sleep:, steps:, day:) because a facet's identity is the source plus the identity values and does not include the type.
timestamp: 2026-10-17T00:00:00Z
resource: garmin/run.py#days
anchor: "Ids name what they are"
basis: code
tier: detail
alternatives:
  - Use the bare date as the id for each daily type, which makes steps, sleep and the day record one facet that supersedes itself.
  - Add the type to the identity key, which is a change to Anam and every Definition.
affects:
  - /components/importer-garmin.md
  - /terms/identity-key.md
---

**Choice.** `sleep:<day>`, `steps:<day>`, `day:<day>`, `garmin:session:<UTC start>`. The Concept2 importer follows with `concept2:session:<result id>`, the OwnTracks importer with `loc:<device>:<hour>` and the stays importer with `stay:<device>:<start>`.

`health.heart-rate.day` keys on the bare day (anam card 205), the one daily type that does, so it collides with none; a second daily type keyed on the bare day would need a prefix.

**Why.** Two of Garmin's daily types keyed on a bare date would be one facet, and the second would supersede the first. Making the id carry the type needs no help from Anam. The comment in `days` says so in the code, so the reason travels with it.
