import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, run_plugin, withings_db

ENTRY = REPO / "withings" / "run.py"

GROUPS = [
    {"id": 101, "attrib": 0, "model": "Body Smart", "deviceid": "ab12", "timezone": "Australia/Sydney",
     "date": "2026-10-09 07:30:00", "measures": [(1, 80.5), (6, 29.371)]},
    {"id": 102, "attrib": 1, "model": "Body Smart", "deviceid": "ab12", "timezone": "Australia/Sydney",
     "date": "2026-10-09 08:00:00", "measures": [(1, 99.0)]},
]


class WithingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = withings_db(Path(self.tmp.name) / "withings.db", GROUPS)
        self.config = {"db_path": str(self.db), "person_id": "matt"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_poll_shapes_every_measurement(self):
        r = run_plugin(ENTRY, {"command": "poll", "config": self.config})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(len(r["events"]), 1)
        batch = r["events"][0]
        self.assertEqual(batch["type"], "anam_withings.batch")
        envs = batch["payload"]["envelopes"]
        self.assertEqual([e["payload"]["value"] for e in envs], ["80.5", "29.371", "99.0"])
        self.assertEqual(envs[0]["payload"], {
            "withings_id": "101", "date": "2026-10-09 07:30:00", "type": "1", "value": "80.5", "unit": "-3",
            "attrib": "0", "model": "Body Smart", "deviceid": "ab12", "timezone": "Australia/Sydney"})
        self.assertEqual(envs[0]["asserted_person"], "matt")
        self.assertNotIn("asserted_person", envs[2], "an ambiguous group asserts no one")
        self.assertEqual(len(batch["payload"]["definitions"]), 1)

    def test_handle_shapes_one_group(self):
        r = run_plugin(ENTRY, {"command": "handle", "config": self.config,
                               "event": {"type": "withings.measurement_recorded", "payload": {"withings_id": 102}}})
        self.assertEqual(r["status"], "ok", r)
        envs = r["events"][0]["payload"]["envelopes"]
        self.assertEqual([e["payload"]["withings_id"] for e in envs], ["102"])

    def test_a_reconcile_resends_everything(self):
        r = run_plugin(ENTRY, {"command": "handle", "config": self.config,
                               "event": {"type": "withings.reconciled", "payload": {"groups_held": 2}}})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(len(r["events"][0]["payload"]["envelopes"]), 3)

    def test_a_database_without_attribution_is_refused(self):
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE measure_groups")
        conn.commit()
        conn.close()
        r = run_plugin(ENTRY, {"command": "poll", "config": self.config})
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["retry"])
        self.assertIn("measure_groups", r["error"])

    def test_health(self):
        r = run_plugin(ENTRY, {"command": "health", "config": self.config})
        self.assertEqual(r["status"], "ok", r)


if __name__ == "__main__":
    unittest.main()
