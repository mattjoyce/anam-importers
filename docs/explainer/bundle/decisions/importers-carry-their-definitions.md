---
type: decision
title: Importers carry the Definitions they emit and publish them on first use
description: Each importer ships the Definition files for its types and validates against them, and anam_submit registers a missing one, while types Anam already bundles are carried by nobody here.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/definitions.py#load
anchor: "manifests for one type is an error"
basis: code
tier: supporting
alternatives:
  - Anam bundles every Definition, which makes each new source a change to Anam and puts vendor vocabulary inside it.
  - An operator registers Definitions by hand before the first run, which separates the schema from the code that shapes to it.
affects:
  - /components/definitions.md
  - /components/importer-records.md
  - /terms/facet-definition.md
  - /change-paths/add-a-definition-version.md
---

**Choice.** `load` reads the folder's manifests, the current one of each type and, under `definitions/history/<type>.v<n>.json`, every earlier version of the types the importer emits now (anam card 198). Every batch event carries them all as text, each type's oldest first, since Anam refuses a version older than one it holds; a history file under an old name, which a rename carried away, is Anam's and is not sent. `ensure_published` registers a missing one and refuses a different body at a held version. The records and documents importers are the exception, because the types they send are bundled in Anam, so they carry none and rely on `current_versions`.

**Why.** The importer is the author of the shape, so the contract and the code that meets it are versioned together, and local `check` makes the importer and Anam agree before anything is sent. Anam stays vendor-neutral.

**What it costs.** An importer with no Definition cannot validate locally, so the records importer's duplicate guard is the only local check on a hand-written file.
