---
type: term
title: Asserted subject
description: The subject id an envelope claims the data is about, set from the plugin's person_id config, or left out when the source cannot say.
timestamp: 2026-10-17T00:00:00Z
---

Anam binds each envelope to the one subject it records, at high assurance when the importer asserts that subject and at medium when it asserts nobody. Every importer sets `asserted_subject` from its `person_id` config, which keeps its old name as the importers' own key. The Withings importer leaves it out for a measurement group the scale marked ambiguous (the reading may belong to another user of the scale), so that reading binds at medium.

The wire name was `asserted_person` until anam card 270a. Anam from that card reads both names, and a build from before it reads only the old one, so `anam_submit` asks `GET /v1/status` and sends `asserted_person` to a daemon whose status names no `subject`. The file keeps its old name so links to it hold.
