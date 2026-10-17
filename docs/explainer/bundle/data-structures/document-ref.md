---
type: data-structure
title: Document reference
description: One entry in a batch event's documents list, naming a document's folder-relative path and the local file whose bytes anam_submit posts to Anam's library.
timestamp: 2026-10-17T00:00:00Z
resource: documents/run.py#describe
anchor: 'return env, {"path": rel, "file": str(path)}'
basis: code
tier: detail
group: wire
references: []
---

`{path, file}`. `path` is the identity of the matching `doc.reference` envelope and lends the stored file its extension. `file` is where `anam_submit` reads the bytes, so no bytes ride in an event. Anam names the stored file by its sha256.
