"""anam_garmin: heart rate alerts read from monitoring FIT files as the health ETL's
fit_events.py read them. The plugin and the fixture writer run under uv, which
brings the FIT SDK; without uv the tests are skipped."""

import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

GARMIN = REPO / "garmin" / "run.py"
FIXTURE = REPO / "tests" / "fit_fixture.py"
SUBMIT = REPO / "anam_submit" / "run.py"
UV = shutil.which("uv")


def write_fit(path: Path, events) -> Path:
    subprocess.run([UV, "run", "-q", "--script", str(FIXTURE), str(path)], input=json.dumps(events),
                   text=True, check=True, timeout=120)
    return path


def run(command, fit_dir, **config):
    request = {"command": command, "config": {"fit_dir": str(fit_dir), "person_id": "person-a", **config}}
    out = subprocess.run([UV, "run", "-q", "--script", str(GARMIN)], input=json.dumps(request),
                         capture_output=True, text=True, check=True, timeout=120)
    return json.loads(out.stdout)


def payloads(r):
    return [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]


@unittest.skipUnless(UV, "no uv to run the plugin under")
class AlertTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "Monitoring"
        self.dir.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_an_alert_is_the_health_db_worker_s_payload_and_other_events_are_not_alerts(self):
        write_fit(self.dir / "2026" / "a_WELLNESS.fit", [
            ["2026-09-25T11:31:00+00:00", 66, (117 << 8) | 100],
            ["2026-09-25T12:00:00+00:00", 22, 5],
        ])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [{"source": "garmin", "kind": "hr_high_alert", "fact_time": "2026-09-25T11:31:00Z",
                                        "heart_rate": 117, "threshold": 100, "unit": "bpm"}])
        self.assertIn("117", json.dumps(payloads(r)[0]))
        self.assertNotIn("117.0", json.dumps(payloads(r)[0]))

    def test_the_same_alert_in_two_files_is_sent_once(self):
        alert = ["2026-09-25T11:31:00+00:00", 66, (117 << 8) | 100]
        write_fit(self.dir / "a_WELLNESS.fit", [alert])
        write_fit(self.dir / "b_WELLNESS.fit", [alert, ["2026-09-26T08:00:00+00:00", 66, (121 << 8) | 100]])
        r = run("poll", self.dir)
        self.assertEqual([p["fact_time"] for p in payloads(r)], ["2026-09-25T11:31:00Z", "2026-09-26T08:00:00Z"])

    def test_poll_is_a_snapshot_and_handle_reads_only_recent_files(self):
        old = write_fit(self.dir / "old_WELLNESS.fit", [["2026-01-01T00:00:00+00:00", 66, (130 << 8) | 100]])
        write_fit(self.dir / "new_WELLNESS.fit", [["2026-09-25T11:31:00+00:00", 66, (117 << 8) | 100]])
        week_ago = time.time() - 7 * 86400
        os.utime(old, (week_ago, week_ago))
        polled = run("poll", self.dir)
        self.assertEqual(len(payloads(polled)), 2)
        self.assertEqual(polled["events"][0]["payload"]["snapshot"]["types"], ["health.heart-rate-alert"])
        handled = run("handle", self.dir)
        self.assertEqual([p["heart_rate"] for p in payloads(handled)], [117])
        self.assertNotIn("snapshot", handled["events"][0]["payload"])

    def test_a_file_that_will_not_decode_is_logged_and_the_run_is_no_snapshot(self):
        write_fit(self.dir / "a_WELLNESS.fit", [["2026-09-25T11:31:00+00:00", 66, (117 << 8) | 100]])
        (self.dir / "b_WELLNESS.fit").write_bytes(b"not a FIT file")
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(len(payloads(r)), 1)
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertTrue(any("b_WELLNESS.fit" in line["message"] for line in r.get("logs", [])), r.get("logs"))
        self.assertEqual(run("health", self.dir)["status"], "error")

    def test_a_missing_fit_dir_is_not_retried(self):
        r = run("poll", self.dir / "nowhere")
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_alerts_are_admitted_under_the_bundled_definition_and_a_resend_is_no_op(self):
        write_fit(self.dir / "a_WELLNESS.fit", [["2026-09-25T11:31:00+00:00", 66, (117 << 8) | 100],
                                                ["2026-09-26T08:00:00+00:00", 66, (121 << 8) | 100]])
        daemon = Daemon("garmin", ["health.heart-rate-alert"])
        try:
            shaped = run("poll", self.dir)
            for want in ("admitted", "no-op"):
                for ev in shaped["events"]:
                    r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                            "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                            "secrets": {"anam_importer_token_test": daemon.token}})
                    self.assertEqual(r["status"], "ok", r)
                    self.assertEqual(r["events"][0]["payload"]["outcomes"], {want: 2})
        finally:
            daemon.close()


if __name__ == "__main__":
    unittest.main()
