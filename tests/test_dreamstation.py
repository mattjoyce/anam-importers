"""anam_dreamstation against a DreamStation card copy. DREAMSTATION_CARD names one
(the P-SERIES directory) and the dreamstation package must import; the tests that
need a card are skipped without both, and those that need Anam without ANAM_BIN."""

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

DS = REPO / "dreamstation_card" / "run.py"
SUBMIT = REPO / "anam_submit" / "run.py"
CARD = os.environ.get("DREAMSTATION_CARD", "")
HAVE_CARD = bool(CARD) and importlib.util.find_spec("dreamstation") is not None


def run(command, card):
    return run_plugin(DS, {"command": command, "config": {"card_path": str(card), "person_id": "person-a"}})


class NoCardTest(unittest.TestCase):
    def test_a_missing_card_copy_is_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            r = run("poll", Path(d) / "P-SERIES")
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])
        self.assertIn("no card copy", r["error"])


@unittest.skipUnless(HAVE_CARD, "DREAMSTATION_CARD unset or the dreamstation package missing")
class CardTest(unittest.TestCase):
    def test_every_session_holds_only_what_the_device_wrote(self):
        r = run("poll", CARD)
        self.assertEqual(r["status"], "ok", r)
        payloads = [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]
        self.assertTrue(payloads)
        derived = {"ahi", "rdi", "end", "mask_on_seconds", "leak", "span_seconds", "session_hex"}
        for p in payloads:
            self.assertFalse(derived & p.keys(), p.keys())
        self.assertEqual(len({(p["device_serial"], p["session"]) for p in payloads}), len(payloads))

    def test_health_says_every_session_conforms(self):
        r = run("health", CARD)
        self.assertEqual(r["status"], "ok", r)

    def test_a_whole_card_is_a_snapshot_and_one_with_an_orphaned_events_file_is_not(self):
        r = run("poll", CARD)
        self.assertTrue(all("snapshot" in ev["payload"] for ev in r["events"]))
        with tempfile.TemporaryDirectory() as d:
            copy = Path(d) / "P-SERIES"
            shutil.copytree(CARD, copy, ignore=shutil.ignore_patterns("*.005"))
            summary = next(f for f in sorted(copy.rglob("*.001")) if f.with_suffix(".002").exists())
            summary.unlink()  # its events file stays: part of a session the run cannot send
            r = run("poll", copy)
            self.assertEqual(r["status"], "ok", r)
            self.assertTrue(r["events"])
            self.assertFalse(any("snapshot" in ev["payload"] for ev in r["events"]))
            self.assertIn("so a run is no snapshot", run("health", copy)["result"])

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_the_card_registers_its_definition_and_a_resend_is_all_no_op(self):
        daemon = Daemon("dreamstation", ["health.cpap-session"])
        try:
            shaped = run("poll", CARD)
            sessions = sum(len(ev["payload"]["envelopes"]) for ev in shaped["events"])
            for want in ("admitted", "no-op"):
                total = 0
                for ev in shaped["events"]:
                    r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                            "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                            "secrets": {"anam_importer_token_test": daemon.token}})
                    self.assertEqual(r["status"], "ok", r)
                    self.assertEqual(set(r["events"][0]["payload"]["outcomes"]), {want})
                    total += r["events"][0]["payload"]["outcomes"][want]
                self.assertEqual(total, sessions)
        finally:
            daemon.close()


if __name__ == "__main__":
    unittest.main()
