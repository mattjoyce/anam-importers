"""The importer and anam_submit against a real Anam daemon. ANAM_BIN names the
binary (make build in the anam repo); without it these are skipped."""

import os
import tempfile
import unittest
from pathlib import Path

from anam_importer import AnamError, Client, Refused, ensure_published, load, parse
from tests.helpers import REPO, Daemon, run_plugin, withings_db
from tests.test_withings import GROUPS

SUBMIT = REPO / "anam_submit" / "run.py"
WITHINGS = REPO / "withings" / "run.py"


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN is not set")
class AgainstAnamTest(unittest.TestCase):
    def setUp(self):
        self.daemon = Daemon("withings", ["health.measurement.withings", "test.reading"])
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.daemon.close()
        self.tmp.cleanup()

    def submit(self, event):
        return run_plugin(SUBMIT, {"command": "handle", "config": {"anam_url": self.daemon.url, "token_secret": "anam_importer_token_test"},
                                   "secrets": {"anam_importer_token_test": self.daemon.token}, "event": event})

    def test_withings_through_anam_submit(self):
        db = withings_db(Path(self.tmp.name) / "withings.db", GROUPS)
        shaped = run_plugin(WITHINGS, {"command": "poll", "config": {"db_path": str(db), "person_id": "person-a"}})
        first = self.submit(shaped["events"][0])
        self.assertEqual(first["status"], "ok", first)
        self.assertEqual(first["events"][0]["payload"]["outcomes"], {"admitted": 3})
        again = self.submit(shaped["events"][0])
        self.assertEqual(again["events"][0]["payload"]["outcomes"], {"no-op": 3})

    def test_a_complete_resend_reports_what_the_source_no_longer_holds(self):
        db = withings_db(Path(self.tmp.name) / "withings.db", GROUPS)
        config = {"db_path": str(db), "person_id": "person-a"}

        def resend():
            shaped = run_plugin(WITHINGS, {"command": "poll", "config": config})
            return [self.submit(ev) for ev in shaped["events"]]

        first = resend()
        self.assertTrue(all(r["status"] == "ok" for r in first), first)
        self.assertIn("snapshot complete, 0 of 3 live absent", first[-1]["result"])
        self.assertEqual([e["type"] for r in first for e in r["events"]], ["anam.admitted"])

        # Withings drops group 102 (one measurement): the next complete resend says so,
        # once, and retracts nothing.
        import sqlite3
        conn = sqlite3.connect(db)
        conn.execute("DELETE FROM measurements WHERE withings_id = 102")
        conn.commit()
        conn.close()
        second = resend()
        alerts = [e for r in second for e in r["events"] if e["type"] == "anam.snapshot_absent"]
        self.assertEqual(len(alerts), 1, second)
        self.assertEqual(alerts[0]["payload"]["absent"], 1)
        self.assertEqual(alerts[0]["payload"]["live"], 3)
        self.assertEqual(alerts[0]["payload"]["types"], ["health.measurement.withings"])
        self.assertEqual(len(alerts[0]["payload"]["absent_ids"]), 1)
        self.assertEqual(alerts[0]["dedupe_key"], "anam.snapshot_absent:" + alerts[0]["payload"]["snapshot"])

    def test_an_incremental_run_is_no_snapshot(self):
        db = withings_db(Path(self.tmp.name) / "withings.db", GROUPS)
        shaped = run_plugin(WITHINGS, {"command": "handle", "config": {"db_path": str(db), "person_id": "person-a"},
                                       "event": {"type": "withings.measurement_recorded", "payload": {"withings_id": 101}}})
        self.assertNotIn("snapshot", shaped["events"][0]["payload"])
        r = self.submit(shaped["events"][0])
        self.assertEqual(r["status"], "ok", r)
        self.assertNotIn("snapshot", r["result"])

    def test_a_refused_batch_is_not_retried(self):
        d = load(REPO / "withings")["health.measurement.withings"]
        bad = {"envelopes": [{"type": d.type, "definition_version": d.version, "payload": {"withings_id": "1"}}],
               "definitions": [d.body.decode()]}
        r = self.submit({"type": "anam_withings.batch", "payload": bad})
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["retry"])
        self.assertTrue(any("envelope 0" in log["message"] for log in r["logs"]), r)

    def test_a_definition_anam_lacks_is_registered_and_one_it_bundles_left_alone(self):
        client = Client(self.daemon.url, self.daemon.token)
        reading = parse(b'''{"meta": {"facet_type": "test.reading", "definition_version": 1,
            "classification": "Normal", "validation_mode": "strict", "source_schema": "test/reading",
            "time_semantics": {"fact_time": {"pointer": "/at", "layout": "2006-01-02T15:04:05Z07:00", "zone": "UTC"}},
            "identity_key": ["/id"]},
          "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object",
            "required": ["id", "at"], "properties": {"id": {"type": "string", "minLength": 1},
            "at": {"type": "string", "minLength": 1}}, "additionalProperties": false}}''')
        bundled = load(REPO / "withings")["health.measurement.withings"]
        ensure_published(client, [reading, bundled])
        ensure_published(client, [reading, bundled])
        self.assertEqual(client.definition("test.reading", 1), reading.manifest)
        admitted = client.submit([{"type": "test.reading", "definition_version": 1,
                                   "payload": {"id": "r-1", "at": "2026-10-09T07:30:00Z"}}])
        self.assertEqual(admitted["changed"], 1)

        changed = parse(reading.body.replace(b'"Normal"', b'"Sensitive"'))
        self.assertNotEqual(changed.manifest, reading.manifest)
        with self.assertRaises(AnamError) as caught:
            ensure_published(client, [changed])
        self.assertFalse(caught.exception.retry)

    def test_the_wrong_token_is_not_retried(self):
        with self.assertRaises(AnamError) as caught:
            Client(self.daemon.url, "not-the-token").submit([])
        self.assertEqual(caught.exception.status, 401)
        self.assertFalse(caught.exception.retry)
        self.assertNotIsInstance(caught.exception, Refused)


if __name__ == "__main__":
    unittest.main()
