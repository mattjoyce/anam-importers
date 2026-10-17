---
type: component
title: anam_dreamstation
description: Decodes a copy of a CPAP machine's SD card with the dreamstation package and sends every session as sleep.cpap-session, a type Anam does not bundle, so it registers its own Definition.
timestamp: 2026-10-17T00:00:00Z
resource: dreamstation_card/run.py#batch_events
anchor: "def batch_events(request: Dict[str, Any]) -> Dict[str, Any]:"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/plugin-protocol.md
---

Source `dreamstation`, type `sleep.cpap-session` v1, identity `/device_serial` with `/session`, fact time `/start` in UTC. The card holds every session since first use, so every run sends the whole card, and `handle` and `poll` are the same function.

`payload` keeps what the device wrote (settings, pressure summary, device counts, an event tally, mask-on spans) and leaves out derived figures such as AHI, which are reads over the facets. A card the decoder cannot read is a non-retryable failure, and an I/O error is retryable. The run is a snapshot unless the decoder reported skipped files, meaning an events file whose summary is not on the card. The decoder is a separate package pinned in the uv script header (Python 3.11 or later), and an absent package fails the run. Keys are `card_path` and `person_id`.
