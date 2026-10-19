---
type: workflow
title: Remember a file without holding it
description: A folder of notes, photos or screenshots becomes record.link envelopes that carry each file's name, hash, size and date and never its bytes, and a file the importer stops finding is superseded with unseen rather than retracted.
timestamp: 2026-10-19T00:00:00Z
resource: links/run.py#poll
anchor: "known, payloads, unseen = reconcile(known, found.seen, now, s.unseen_after)"
basis: code
tier: supporting
trigger: A folder watcher sees a file change under links_dir and runs handle, or a schedule or a person runs poll. They do the same thing, and each is one complete run.
steps:
  - actor: /components/importer-links.md
    caller: /components/ductile-gateway.md
    label: read and check the instance's config
    action: "`settings` reads `links_dir`, `root_name`, `person_id`, `identity` (`path`, `content` or `id`), `zone`, `state_file` and `unseen_after` once, and refuses a bad value naming the key. `state_file` is required and may not sit under `links_dir`."
    reads: [/data-structures/plugin-request.md]
    resource: links/run.py#settings
    anchor: 'raise cfg.bad("state_file", f"{state} is under links_dir, which the importer reads and never writes")'
  - actor: /components/importer-links.md
    label: walk the folder
    action: "`scan` requires `links_dir` to exist, or the run is a retryable failure and no run at all. `files` lists regular files in path order and skips dot-files, dot-directories and symlinks."
    resource: links/run.py#scan
    anchor: 'raise ductile.Failure(f"links_dir {s.links_dir} is not reachable; no run", retry=True)'
  - actor: /components/importer-links.md
    label: date, hash and key each file
    action: "`describe` reads a Markdown file's frontmatter, hashes the file in 1 MiB chunks, takes the first date that answers (frontmatter, EXIF, a file-name prefix, mtime) and composes the `id` under the instance's mode. A file it cannot read or date is skipped and reported, and the run goes on."
    writes: [/data-structures/envelope.md]
    resource: links/run.py#describe
    anchor: 'payload["id"] = f"path:{s.root_name}/{rel}"'
  - actor: /components/importer-links.md
    label: carry the known files
    action: "`reconcile` sends every file seen as observed and every known file not seen as it was, until `unseen_after` complete runs have missed it; then with `unseen: true`, `unseen_since` and `last_seen`. The state is written whole to `state_file`."
    resource: links/run.py#reconcile
    anchor: 'payload.update({"unseen": True, "unseen_since": kept["unseen_since"], "last_seen": kept["last_seen"]})'
  - actor: /components/importer-links.md
    label: emit the batches
    action: "Each batch event carries the envelopes and the `record.link` manifest and is labelled `links i/n`. The run is a snapshot of `record.link` unless a file went unread."
    writes: [/data-structures/batch-event.md]
    resource: links/run.py#poll
    anchor: "if not found.unread:"
  - actor: /components/anam-submit.md
    caller: /components/ductile-gateway.md
    label: post the envelopes
    action: "The batch names no documents, so nothing is posted to the library. The envelopes go through the same path as every other, as in [submit a batch](/workflows/submit-a-batch.md); Anam admits a `record.link` whose sha256 its library does not hold."
    ends: true
    resource: anam_submit/run.py#handle
    anchor: "admission = client.submit(envelopes, snapshot)"
---

Unseen is a supersession and never a retraction: the earlier version stands as what was, and a file that comes back is superseded back. The count of missed runs is the importer's, in `state_file`; Anam keeps none of it, and the Definition's `handling` block says what `unseen` means so every writer agrees.
