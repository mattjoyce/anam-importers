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
        self.daemon = Daemon("withings", ["health.measurement", "test.reading"])
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.daemon.close()
        self.tmp.cleanup()

    def submit(self, event):
        return run_plugin(SUBMIT, {"command": "handle", "config": {"anam_url": self.daemon.url},
                                   "secrets": {"ANAM_IMPORTER_TOKEN": self.daemon.token}, "event": event})

    def test_withings_through_anam_submit(self):
        db = withings_db(Path(self.tmp.name) / "withings.db", GROUPS)
        shaped = run_plugin(WITHINGS, {"command": "poll", "config": {"db_path": str(db), "person_id": "matt"}})
        first = self.submit(shaped["events"][0])
        self.assertEqual(first["status"], "ok", first)
        self.assertEqual(first["events"][0]["payload"]["outcomes"], {"admitted": 3})
        again = self.submit(shaped["events"][0])
        self.assertEqual(again["events"][0]["payload"]["outcomes"], {"no-op": 3})

    def test_a_refused_batch_is_not_retried(self):
        d = load(REPO / "withings")["health.measurement"]
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
        bundled = load(REPO / "withings")["health.measurement"]
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
