---
type: term
title: Sidecar
description: A .meta.yaml file beside a document that states the document's own date and any title or note, because the date is not in the file's bytes.
timestamp: 2026-10-17T00:00:00Z
---

The [documents importer](/components/importer-documents.md) refuses a file without a sidecar and names the sidecar to write. The sidecar must hold `date: YYYY-MM-DD` and may not declare `path`, `sha256`, `bytes` or `media_type`, which the importer measures from the file. See [Sidecar file](/data-structures/sidecar-file.md).
