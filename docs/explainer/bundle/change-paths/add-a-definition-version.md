---
type: change-path
title: Add a Definition version
description: Changing a payload's shape means a new Definition file at version N+1 and importer code that emits it, never an edit of a version Anam already holds.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/definitions.py#ensure_published
anchor: "Anam publishes another body at this version"
basis: code
tier: supporting
touches:
  - /components/definitions.md
  - /data-structures/definition-manifest.md
  - /invariants/a-held-definition-version-is-never-overwritten.md
  - /decisions/importers-carry-their-definitions.md
  - /gaps/exercise-session-is-carried-twice.md
---

1. **Copy and edit.** Replace the file under `<folder>/definitions/<type>.json` with the new body and a higher `definition_version`. The file keeps its name, since an importer ships one version of each type.
2. **Change the shaping** in `run.py` so payloads follow the new schema. `check` fails any payload that does not.
3. **Check the shared copy.** `exercise.session` lives in both the Garmin and Concept2 folders and must stay byte-identical.
4. **Conformance.** Where the Definition follows a standard, the pinned schema under `tests/conformance` decides. Add a payload to the conformance tests.
5. **Expect a supersession.** A resend under the new version changes the payload of every existing facet of that type, so each is superseded with a new version while the old ones stay in Anam.
6. **Release as a minor version** and say in the changelog which importers emit the new version.
