import json
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
        self.config = {"db_path": str(self.db), "person_id": "person-a"}

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
            "attrib": "0", "model": "Body Smart", "deviceid": "ab12", "timezone": "Australia/Sydney",
            # date is UTC, so source_time names UTC, not the device's timezone (anam card 198).
            "source_time": {"value": "2026-10-09 07:30:00", "zone": "UTC", "basis": "source"}})
        self.assertEqual(envs[0]["asserted_person"], "person-a")
        self.assertNotIn("asserted_person", envs[2], "an ambiguous group asserts no one")
        # Every version of the type it emits, oldest first; the old name's history is not sent.
        self.assertEqual([json.loads(m)["meta"]["definition_version"] for m in batch["payload"]["definitions"]], [1, 2, 3])
        self.assertEqual({json.loads(m)["meta"]["facet_type"] for m in batch["payload"]["definitions"]},
                         {"health.measurement.withings"})

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

    def test_values_are_written_without_exponents(self):
        import sys
        sys.path.insert(0, str(REPO / "withings"))
        from run import render

        cases = {80.5: "80.5", 29.371: "29.371", 99.0: "99.0", 0.00001: "0.00001", 1e16: "10000000000000000.0",
                 -0.5: "-0.5", 1.5e-07: "0.00000015"}
        for value, want in cases.items():
            self.assertEqual(render(value), want, value)
        with self.assertRaises(ValueError):
            render(float("nan"))

    def test_a_tiny_value_still_conforms(self):
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE measurements SET value = 0.00001 WHERE withings_id = 102")
        conn.commit()
        conn.close()
        r = run_plugin(ENTRY, {"command": "poll", "config": self.config})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"][0]["payload"]["envelopes"][2]["payload"]["value"], "0.00001")

    def test_a_database_without_measurements_is_a_protocol_error(self):
        import sqlite3
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE measurements")
        conn.commit()
        conn.close()
        r = run_plugin(ENTRY, {"command": "poll", "config": self.config})
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])
        self.assertIn("measurements", r["error"])

    def test_a_locked_database_is_retried(self):
        import sqlite3
        holder = sqlite3.connect(self.db, isolation_level=None)
        holder.execute("PRAGMA journal_mode=DELETE")
        holder.execute("BEGIN EXCLUSIVE")
        try:
            r = run_plugin(ENTRY, {"command": "poll", "config": {**self.config, "busy_timeout_ms": 100}})
        finally:
            holder.execute("ROLLBACK")
            holder.close()
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(r["retry"], r)

    def test_health(self):
        r = run_plugin(ENTRY, {"command": "health", "config": self.config})
        self.assertEqual(r["status"], "ok", r)


if __name__ == "__main__":
    unittest.main()
