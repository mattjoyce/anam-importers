import re
import unittest

import anam_importer
from tests.helpers import REPO


class VersionTest(unittest.TestCase):
    """One version for the repo: VERSION, the base, every plugin manifest and the
    changelog's newest release all say the same thing."""

    def test_the_version_is_semver(self):
        self.assertRegex(anam_importer.__version__, r"^\d+\.\d+\.\d+$")

    def test_every_manifest_carries_it(self):
        for manifest in sorted(REPO.glob("*/manifest.yaml")):
            found = re.search(r"^version:\s*(\S+)", manifest.read_text(), re.M)
            self.assertIsNotNone(found, manifest)
            self.assertEqual(found.group(1), anam_importer.__version__, manifest)

    def test_the_changelog_names_it(self):
        releases = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", (REPO / "CHANGELOG.md").read_text(), re.M)
        self.assertTrue(releases, "CHANGELOG.md names no release")
        self.assertEqual(releases[0], anam_importer.__version__)


if __name__ == "__main__":
    unittest.main()
