---
type: change-path
title: Release a new version
description: Move the changelog's unreleased entries under the new number, set VERSION and every manifest to it, commit, tag, and lock the changed plugins on the gateway.
timestamp: 2026-10-17T00:00:00Z
resource: tests/test_version.py#VersionTest
anchor: "def test_the_changelog_names_it(self):"
basis: code
tier: detail
touches:
  - /invariants/the-repo-has-one-version.md
  - /data-structures/plugin-manifest.md
---

1. **Pick the bump.** Major for a change an existing importer or gateway config must follow (a renamed event, a changed batch payload, a removed base function). Minor for a new importer, command, base function or Definition version. Patch for a fix that changes no interface.
2. **Edit** `CHANGELOG.md` (move Unreleased under `## [X.Y.Z]`), `VERSION`, and `version:` in every plugin's `manifest.yaml`.
3. **Run the unit tests.** `test_version.py` fails on any disagreement.
4. **Tag and push** `vX.Y.Z`.
5. **Lock on the gateway.** A gateway that runs these plugins needs `ductile plugin lock` for each changed one.
