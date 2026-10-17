---
type: term
title: Identity key
description: The list of payload fields a Definition composes a facet's identity from, so an importer must send those fields and nothing else decides which fact a row is.
timestamp: 2026-10-17T00:00:00Z
---

Each Definition's `meta.identity_key` lists JSON pointers into the payload. Anam joins their values with the source name to get the facet's identity. The key varies by type, for example `/withings_id` with `/type` for a Withings measurement, `/date_excel` with `/reading` for a blood pressure reading, `/device_serial` with `/session` for a CPAP session, and `/id` for most others.

An importer therefore writes the fields the key names, an ordinal or an id string, and leaves composition to Anam. The Garmin importer prefixes its ids (`sleep:`, `steps:`, `day:`) because the type is not part of the identity, so two types keyed on a bare date would collide. See [the identity gap](/gaps/writing-an-id-field-is-the-edge-of-shaping.md).
