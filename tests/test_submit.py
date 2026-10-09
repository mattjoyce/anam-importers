"""anam_submit's own checks, before it reaches Anam."""

import unittest
from pathlib import Path

from tests.helpers import run_plugin

SUBMIT = Path(__file__).resolve().parent.parent / "anam_submit" / "run.py"
BATCH = {"type": "anam_withings.batch", "payload": {"envelopes": [{"type": "t", "definition_version": 1, "payload": {}}]}}


class TokenSecretTest(unittest.TestCase):
    def handle(self, config, secrets):
        return run_plugin(SUBMIT, {"command": "handle", "config": config, "secrets": secrets, "event": BATCH})

    def test_the_token_is_the_secret_config_names_and_nothing_else(self):
        cases = [
            ("no token_secret", {"anam_url": "http://127.0.0.1:9"}, {"anam_importer_token_withings": "t"},
             "no token_secret"),
            ("the named secret not granted", {"anam_url": "http://127.0.0.1:9", "token_secret": "anam_importer_token_withings"},
             {"anam_importer_token_other": "t"}, "no anam_importer_token_withings secret"),
        ]
        for name, config, secrets, want in cases:
            with self.subTest(name):
                r = self.handle(config, secrets)
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"])
                self.assertIn(want, r["error"])


if __name__ == "__main__":
    unittest.main()
