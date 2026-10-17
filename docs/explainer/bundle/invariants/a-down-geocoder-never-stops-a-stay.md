---
type: invariant
title: A geocoder that is down never stops a stay
description: The geocoder returns nothing on any network or parse failure, so a stay is sent without a place and the place backfills on a later run.
timestamp: 2026-10-17T00:00:00Z
resource: stays/geocode.py#Nominatim
anchor: "Never raises"
basis: code
tier: detail
enforced_at: stays/geocode.py#Nominatim
enforced_anchor: "except (OSError, http.client.HTTPException, ValueError):"
applies_to:
  - /components/geocoder.md
  - /components/importer-stays.md
tested_by:
  - tests/test_stays.py#test_handle_emits_a_conforming_placeless_stay
---

A cache read or write that fails is also not an error. The worst a broken cache does is a repeat call. An unnamed cell is not cached, so the next run tries it again.
