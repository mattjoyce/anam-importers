---
type: term
title: Asserted person
description: The person id an envelope claims the data belongs to, set from the plugin's person_id config, or left out when the source cannot say.
timestamp: 2026-10-17T00:00:00Z
---

Anam binds each envelope to the one person it records, at high assurance when the importer asserts that person and at medium when it asserts nobody. Every importer sets `asserted_person` from its `person_id` config. The Withings importer leaves it out for a measurement group the scale marked ambiguous (the reading may belong to another user of the scale), so that reading binds at medium.
