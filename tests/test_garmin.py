"""anam_garmin: heart rate alerts read from monitoring FIT files as the health ETL's
fit_events.py read them. The plugin and the fixture writer run under uv, which
brings the FIT SDK; without uv the tests are skipped."""

import json
import os
import shutil
import sqlite3
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


Z = "00:00:00.000000"
DAILY_SUMMARY = f"""CREATE TABLE daily_summary (day DATE NOT NULL, hr_min INTEGER, hr_max INTEGER, rhr INTEGER,
    stress_avg INTEGER, step_goal INTEGER, steps INTEGER, moderate_activity_time TIME NOT NULL DEFAULT '{Z}',
    vigorous_activity_time TIME NOT NULL DEFAULT '{Z}', intensity_time_goal TIME NOT NULL DEFAULT '{Z}',
    floors_up FLOAT, floors_down FLOAT, floors_goal FLOAT, distance FLOAT, calories_goal INTEGER,
    calories_total INTEGER, calories_bmr INTEGER, calories_active INTEGER, calories_consumed INTEGER,
    hydration_goal INTEGER, hydration_intake INTEGER, sweat_loss INTEGER, spo2_avg FLOAT, spo2_min FLOAT,
    rr_waking_avg FLOAT, rr_max FLOAT, rr_min FLOAT, bb_charged INTEGER, bb_max INTEGER, bb_min INTEGER,
    description VARCHAR, PRIMARY KEY (day))"""

# A day as GarminDB 3.6.7 wrote 2026-10-09, and one the watch recorded nothing for.
DAY = {"day": "2026-10-09", "hr_min": 59, "hr_max": 135, "rhr": 61, "stress_avg": 30, "step_goal": 5070,
       "steps": 6219, "moderate_activity_time": "00:24:00.000000", "intensity_time_goal": "02:30:00.000000",
       "floors_up": 10.0, "floors_down": 5.55282, "floors_goal": 10.0, "distance": 4.788, "calories_total": 2238,
       "calories_bmr": 1976, "calories_active": 262, "hydration_goal": 2800, "rr_waking_avg": 14.0,
       "rr_max": 26.0, "rr_min": 11.0, "bb_charged": 47, "bb_max": 63, "bb_min": 13}
EMPTY_DAY = {"day": "2026-10-02", "intensity_time_goal": "02:30:00.000000", "hydration_goal": 2800}


def garmin_db(path: Path, nights, resting=(), daily=()) -> Path:
    """A garmin.db in GarminDB 3.6.7's shape: nights in its sleep table, (day, bpm)
    in resting_hr, and (day, hr_min, hr_max) in daily_summary, its other columns
    left empty."""
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE sleep (day DATE NOT NULL, start DATETIME, "end" DATETIME, total_sleep TIME NOT NULL,
        deep_sleep TIME NOT NULL, light_sleep TIME NOT NULL, rem_sleep TIME NOT NULL, awake TIME NOT NULL,
        avg_spo2 FLOAT, avg_rr FLOAT, avg_stress FLOAT, score INTEGER, qualifier VARCHAR, PRIMARY KEY (day))""")
    conn.execute("CREATE TABLE resting_hr (day DATE NOT NULL, resting_heart_rate FLOAT, PRIMARY KEY (day))")
    conn.execute(DAILY_SUMMARY)
    conn.executemany("INSERT INTO sleep VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", nights)
    conn.executemany("INSERT INTO resting_hr VALUES (?, ?)", resting)
    for row in daily:
        row = dict(zip(("day", "hr_min", "hr_max"), row)) if isinstance(row, tuple) else row
        conn.execute(f"INSERT INTO daily_summary ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))
    conn.commit()
    conn.close()
    return path


NIGHT = ("2026-10-08", "2026-10-07 12:44:00.000000", "2026-10-07 18:42:00.000000", "05:49:00.000000",
         "01:18:00.000000", "03:06:00.000000", "01:25:00.000000", "00:09:00.000000", None, 14.0, 19.0, 75, "FAIR")
NO_SLEEP = ("2026-10-01", None, None, Z, Z, Z, Z, Z, None, None, None, None, None)


def run(command, fit_dir, **config):
    db = Path(fit_dir).parent / "garmin.db"
    if not db.exists():
        garmin_db(db, [])
    request = {"command": command, "config": {"fit_dir": str(fit_dir), "garmin_db": str(db), "person_id": "person-a",
                                              **config}}
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
        self.assertEqual(polled["events"][0]["payload"]["snapshot"]["types"], ["garmin.day", "health.heart-rate-alert", "health.heart-rate-daily", "health.step-count", "sleep.episode"])
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

    def test_a_night_is_the_ieee_body_with_garmin_s_fields_beside_it(self):
        garmin_db(self.dir.parent / "garmin.db", [NIGHT, NO_SLEEP])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [{
            "id": "sleep:2026-10-08",
            "effective_time_frame": {"time_interval": {"start_date_time": "2026-10-07T12:44:00Z",
                                                       "end_date_time": "2026-10-07T18:42:00Z"}},
            "total_sleep_time": {"value": 349, "unit": "min"},
            "light_sleep_duration": {"value": 186, "unit": "min"},
            "deep_sleep_duration": {"value": 78, "unit": "min"},
            "rem_sleep_duration": {"value": 85, "unit": "min"},
            "wake_after_sleep_onset": {"value": 9, "unit": "min"},
            "is_main_sleep": True, "score": 75, "qualifier": "FAIR", "avg_rr": 14, "avg_stress": 19,
        }])
        self.assertEqual(r["events"][0]["payload"]["snapshot"]["types"], ["garmin.day", "health.heart-rate-alert", "health.heart-rate-daily", "health.step-count", "sleep.episode"])

    def test_a_day_s_heart_rate_is_three_omh_figures_and_an_empty_one_is_none(self):
        garmin_db(self.dir.parent / "garmin.db", [], resting=[("2026-10-09", 61.0)],
                  daily=[("2026-10-09", 59, 135), ("2026-04-05", None, 120)])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        sydney_day = {"time_interval": {"start_date_time": "2026-10-09T00:00:00+11:00",
                                        "end_date_time": "2026-10-10T00:00:00+11:00"}}
        self.assertEqual(payloads(r), [
            {"id": "2026-04-05", "statistic": "maximum", "heart_rate": {"value": 120, "unit": "beats/min"},
             "effective_time_frame": {"time_interval": {"start_date_time": "2026-04-05T00:00:00+11:00",
                                                        "end_date_time": "2026-04-06T00:00:00+10:00"}},
             "descriptive_statistic": "maximum"},
            {"id": "2026-10-09", "statistic": "resting", "heart_rate": {"value": 61, "unit": "beats/min"},
             "effective_time_frame": sydney_day, "temporal_relationship_to_physical_activity": "at rest"},
            {"id": "2026-10-09", "statistic": "minimum", "heart_rate": {"value": 59, "unit": "beats/min"},
             "effective_time_frame": sydney_day, "descriptive_statistic": "minimum"},
            {"id": "2026-10-09", "statistic": "maximum", "heart_rate": {"value": 135, "unit": "beats/min"},
             "effective_time_frame": sydney_day, "descriptive_statistic": "maximum"},
        ])

    def test_a_day_is_omh_steps_and_garmin_s_record_and_an_empty_day_is_neither(self):
        garmin_db(self.dir.parent / "garmin.db", [], daily=[DAY, EMPTY_DAY])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        by_type = {}
        for ev in r["events"]:
            for e in ev["payload"]["envelopes"]:
                by_type.setdefault(e["type"], []).append(e["payload"])
        self.assertEqual(by_type["health.step-count"], [{
            "id": "steps:2026-10-09", "step_count": {"value": 6219, "unit": "steps"},
            "effective_time_frame": {"time_interval": {"start_date_time": "2026-10-09T00:00:00+11:00",
                                                       "end_date_time": "2026-10-10T00:00:00+11:00"}}}])
        self.assertEqual(by_type["garmin.day"], [{
            "id": "day:2026-10-09", "day": "2026-10-09", "step_goal": 5070, "floors_up": 10, "floors_down": 5.55282, "floors_goal": 10,
            "calories_total": 2238, "calories_bmr": 1976, "calories_active": 262, "hydration_goal": 2800,
            "stress_avg": 30, "rr_waking_avg": 14, "rr_max": 26, "rr_min": 11, "bb_charged": 47, "bb_max": 63,
            "bb_min": 13, "distance_km": 4.788, "moderate_activity_minutes": 24, "vigorous_activity_minutes": 0,
            "intensity_time_goal_minutes": 150}])

    def test_a_missing_fit_dir_is_not_retried(self):
        r = run("poll", self.dir / "nowhere")
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_every_type_is_admitted_and_a_resend_is_no_op(self):
        write_fit(self.dir / "a_WELLNESS.fit", [["2026-09-25T11:31:00+00:00", 66, (117 << 8) | 100],
                                                ["2026-09-26T08:00:00+00:00", 66, (121 << 8) | 100]])
        # The same date in sleep, steps, the day record and heart rate: five types under one
        # source, none of them one facet (anam card 55, identity across types).
        same_day = ("2026-10-09",) + NIGHT[1:]
        garmin_db(self.dir.parent / "garmin.db", [NIGHT, same_day, NO_SLEEP], resting=[("2026-10-09", 61.0)],
                  daily=[DAY, EMPTY_DAY])
        daemon = Daemon("garmin", ["garmin.day", "health.heart-rate-alert", "health.heart-rate-daily",
                                   "health.step-count", "sleep.episode"])
        try:
            shaped = run("poll", self.dir)
            for want in ("admitted", "no-op"):
                got = []
                for ev in shaped["events"]:
                    r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                            "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                            "secrets": {"anam_importer_token_test": daemon.token}})
                    self.assertEqual(r["status"], "ok", r)
                    got.append(r["events"][0]["payload"]["outcomes"])
                self.assertEqual(got, [{want: 2}, {want: 2}, {want: 3}, {want: 1}, {want: 1}])
        finally:
            daemon.close()


if __name__ == "__main__":
    unittest.main()
