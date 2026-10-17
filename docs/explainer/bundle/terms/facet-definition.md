---
type: term
title: Facet Definition
description: A JSON manifest that names a facet type and version, the closed JSON Schema its payload must satisfy, and how its identity and fact time are read from the payload.
timestamp: 2026-10-17T00:00:00Z
---

A Definition has a `meta` block and a `schema`. `meta` holds `facet_type`, `definition_version`, `classification`, `validation_mode`, `time_semantics.fact_time` (a JSON pointer, a layout and a zone), `identity_key` (a list of JSON pointers) and `min_binding_assurance`. See [Definition manifest](/data-structures/definition-manifest.md).

An importer carries the Definitions it emits under `definitions/<type>.json` and validates every payload against them before anything leaves. A type Anam already bundles needs no copy in the importer, as the [records importer](/components/importer-records.md) shows. A version is immutable once Anam holds it, so a change means a new version. See [add a Definition version](/change-paths/add-a-definition-version.md).
