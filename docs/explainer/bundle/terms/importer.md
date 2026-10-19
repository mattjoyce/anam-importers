---
type: term
title: Importer
description: A plugin that reads one source, shapes its rows to a Facet Definition, and emits batch events for anam_submit to post.
timestamp: 2026-10-17T00:00:00Z
---

An importer is a folder with a `manifest.yaml`, a `run.py` and the Definitions it emits. It reads a vendor's native format, builds payloads, wraps each in an [envelope](/terms/envelope.md), validates them locally and emits [batch events](/data-structures/batch-event.md). It holds no token and writes nothing to Anam itself.

The importers on master are [Withings](/components/importer-withings.md), [blood pressure CSV](/components/importer-bp-csv.md), [DreamStation](/components/importer-dreamstation.md), [records](/components/importer-records.md), [documents](/components/importer-documents.md), [Garmin](/components/importer-garmin.md), [Concept2](/components/importer-concept2.md), [OwnTracks](/components/importer-owntracks.md), [stays](/components/importer-stays.md) and [links](/components/importer-links.md). To add one, follow [add an importer](/change-paths/add-an-importer.md).
