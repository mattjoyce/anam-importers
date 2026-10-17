---
type: invariant
title: A Definition version Anam holds is never overwritten
description: ensure_published registers a missing Definition and leaves a held one alone, and stops the run when the held body differs from the importer's, so a version means one thing.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/definitions.py#ensure_published
anchor: "Anam publishes another body at this version"
basis: code
tier: supporting
enforced_at: anam_importer/definitions.py#ensure_published
enforced_anchor: "if published != d.manifest:"
applies_to:
  - /components/definitions.md
  - /components/anam-submit.md
---

A change to a Definition is therefore a new version file and a new `definition_version`, never an edit of a shipped one. The error is not retryable, because only a person can decide which side is right. See [add a Definition version](/change-paths/add-a-definition-version.md).
