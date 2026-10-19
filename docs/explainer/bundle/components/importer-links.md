---
type: component
title: anam_links
description: Sends a folder of files as one snapshot of record.link envelopes, each a file's name, hash, size and date and never its bytes, under one identity mode per folder, and supersedes a file it has not found for unseen_after runs with unseen rather than retracting it.
timestamp: 2026-10-19T00:00:00Z
resource: links/run.py#describe
anchor: "def describe(s: Settings, path: Path)"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

Source `links`, type `record.link`, registered from `links/definitions/record.link.json` with a `handling` block (anam card 165). A link is a file Anam remembers but does not hold: `describe` hashes the file in 1 MiB chunks and sends `path`, `sha256`, `bytes`, `media_type`, `date` and `date_from`, and `anam_submit` posts no document for it. Anam admits a `record.link` whose sha256 its library lacks, because the held-bytes refusal is keyed on `doc.reference`.

One instance is one folder (`links_dir`, named `root_name` in every fact) under one identity mode (`identity`): `path:<root>/<path>`, `content:<sha256>` or `id:<frontmatter id>`, carried as the `id`'s prefix and repeated in `identity`. In `id` mode a file without a declared id is skipped and reported, never keyed by its path.

`fact_time` takes the first of a Markdown file's frontmatter `date`, EXIF `DateTimeOriginal` (`exif_original` reads a JPEG's APP1 segment or a TIFF's first IFDs itself, with no image library), a `YYYY-MM-DD` prefix on the file name, then mtime, reading a zoneless date in the instance's `zone`. mtime is refused for Markdown.

`reconcile` carries every known file in every run, so a run is a snapshot: a file not found is sent as it was until `unseen_after` complete runs have missed it, then with `unseen: true`, `unseen_since` and `last_seen`, and a file that returns is sent as observed again. The count and the last payload per file live in `state_file`, a required key refused under `links_dir`, written whole and renamed into place; an unreachable `links_dir` is a failure worth retrying and no run, and a run in which a file went unread carries no snapshot label.
