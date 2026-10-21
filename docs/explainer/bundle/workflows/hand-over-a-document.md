---
type: workflow
title: Hand over a document
description: A folder of documents with sidecars becomes record.document envelopes, and the file bytes reach Anam's library through anam_submit without ever travelling inside an event.
timestamp: 2026-10-17T00:00:00Z
resource: documents/run.py#poll
anchor: '"documents": [by_path[e["payload"]["path"]] for e in g],'
basis: code
tier: supporting
trigger: A folder watcher sees a file change under documents_dir and runs handle, or a person runs poll. They do the same thing.
steps:
  - actor: /components/importer-documents.md
    caller: /components/ductile-gateway.md
    label: walk the folder
    action: "`scan` requires `documents_dir` to exist. `documents` then lists regular files in path order and skips dot-files, dot-directories, sidecars and symlinks."
    reads: [/data-structures/plugin-request.md]
    resource: documents/run.py#scan
    anchor: 'root = Path(str(config.get("documents_dir", ""))).expanduser()'
  - actor: /components/importer-documents.md
    label: read the sidecar
    action: "The sidecar must exist and hold a `date`. A key that the file decides (`path`, `sha256`, `bytes`, `media_type`) is refused, and a missing sidecar refuses the run and names the file to write."
    reads: [/data-structures/sidecar-file.md]
    resource: documents/run.py#sidecar
    anchor: "is measured from the file, not declared"
  - actor: /components/importer-documents.md
    label: hash and measure the file
    action: "The file is read in 1 MiB chunks for its sha256 and size, and its media type comes from a fixed table, then `mimetypes`, then `application/octet-stream`. The envelope's payload is the sidecar's fields plus those four, and `source_time`: the sidecar's date read in Australia/Sydney, the zone `record.document` reads it in, with basis assumption, logged once a run (anam card 198)."
    writes: [/data-structures/envelope.md, /data-structures/document-ref.md]
    resource: documents/run.py#describe
    anchor: 'payload.update({"path": rel, "sha256": h.hexdigest(), "bytes": size, "media_type": media_type(path),'
  - actor: /components/importer-documents.md
    label: name the files each batch needs
    action: "Each batch event lists `{path, file}` for exactly the documents its envelopes describe, sets `current_versions`, and is labelled `documents i/n`. The run is a snapshot of `record.document`."
    writes: [/data-structures/batch-event.md]
    resource: documents/run.py#poll
    anchor: '"documents": [by_path[e["payload"]["path"]] for e in g],'
  - actor: /components/anam-submit.md
    caller: /components/ductile-gateway.md
    label: read each named file's bytes
    action: "Before it posts envelopes, `handle` reads each `file` from disk. A read failure is a retryable error for that batch."
    reads: [/data-structures/document-ref.md]
    resource: anam_submit/run.py#handle
    anchor: 'data = Path(str(doc["file"])).read_bytes()'
  - actor: /components/anam-client.md
    caller: /components/anam-submit.md
    label: post the bytes to the library
    action: "`store_document` posts the raw bytes to `/v1/documents?ext=`. The name only supplies an extension, so a person browsing the library can open the stored file."
    resource: anam_importer/client.py#store_document
    anchor: 'ext = PurePosixPath(name).suffix.lstrip(".")'
  - actor: /components/anam-daemon.md
    caller: /components/anam-client.md
    label: store the file under its sha256
    action: "Anam names the stored file by its sha256 and answers 201 for new bytes or 200 for bytes it already holds. It refuses a `record.document` whose sha256 its library has no bytes for, which is why the bytes go first."
    resource: README.md#Wiring an importer into a gateway (documents)
    anchor: "stored file by its sha256 (anam card 150) and answers 201 or 200 for bytes it now holds; the path"
  - actor: /components/anam-submit.md
    label: post the record.document envelopes
    action: "With the bytes held, the batch's envelopes go through the same path as every other, as in [submit a batch](/workflows/submit-a-batch.md). A document rescanned under the same name has new bytes, so its reference supersedes the old one and Anam keeps the first bytes."
    ends: true
    resource: anam_submit/run.py#handle
    anchor: "admission = client.submit(envelopes, snapshot)"
---

Bytes never ride in an event, only a path to a file, because an event is a message through the gateway and a document can be large. Only Anam writes its library, and the importer never writes into it. `anam_submit` needs read access to the same folder the importer scans.
