---
type: invariant
title: The repository has one version
description: VERSION, the base package, every plugin manifest and the changelog's newest release all name the same number, and a test fails when one disagrees.
timestamp: 2026-10-17T00:00:00Z
resource: tests/test_version.py#VersionTest
anchor: "class VersionTest(unittest.TestCase):"
basis: code
tier: detail
enforced_at: tests/test_version.py#VersionTest
enforced_anchor: "def test_every_manifest_carries_it(self):"
applies_to:
  - /data-structures/plugin-manifest.md
  - /change-paths/release-a-new-version.md
tested_by:
  - tests/test_version.py#test_the_changelog_names_it
---

`anam_importer.__version__` reads `VERSION`. A gateway that runs these plugins needs `ductile plugin lock` for each changed one after a release.
