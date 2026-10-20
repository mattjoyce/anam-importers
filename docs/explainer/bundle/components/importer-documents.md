---
type: component
title: anam_documents
description: Sends a folder of documents with sidecars as one snapshot of record.document envelopes, each batch naming the files whose bytes anam_submit hands to Anam's library before the envelopes go.
timestamp: 2026-10-17T00:00:00Z
resource: documents/run.py#describe
anchor: "def describe(root: Path, path: Path, person: str)"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/importer-records.md
  - /components/plugin-protocol.md
---

Source `documents`, type `record.document`, carried by Anam, so there is no Definition here. Identity is the folder-relative path. The payload is the sidecar's fields plus `path`, `sha256`, `bytes` and `media_type`, which the importer measures from the file and the sidecar may not declare.

`documents` walks the folder in path order and skips dot-files, dot-directories, sidecars and symlinks. `describe` hashes the file in 1 MiB chunks. `media_type` uses a fixed table of common extensions, then `mimetypes`, then `application/octet-stream`; another spelling would supersede every reference that carries it. The importer reuses the records importer's YAML reader by loading `records/run.py` from its path, so both agree on a sidecar's scalars. See [that coupling](/gaps/documents-load-the-records-importer-by-path.md).

Each batch carries a `documents` list of `{path, file}`. Bytes never travel in an event, only the file path, and `anam_submit` reads the file. See [hand over a document](/workflows/hand-over-a-document.md).
