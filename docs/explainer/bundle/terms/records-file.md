---
type: term
title: Records file
description: A YAML or JSON file of facts written down from a source document by hand or by an extractor script, with the document and extraction method as provenance.
timestamp: 2026-10-17T00:00:00Z
---

A records file has the top-level keys `document`, `extracted` and `records`. Each record names a facet `type` and an `id`, and its other fields are the payload. The [records importer](/components/importer-records.md) sends every file in a folder. One-off exports become records files through the [extractors](/components/record-extractors.md). See [Records file](/data-structures/records-file.md).
