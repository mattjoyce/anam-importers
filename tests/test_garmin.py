"""anam_garmin: heart rate alerts read from monitoring FIT files as the health ETL's
fit_events.py read them, sessions from activity FIT files, and the days in garmin.db. The plugin and the fixture writer run under uv, which
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

# A day in GarminDB 3.6.7's shape (made up), and one the watch recorded nothing for.
DAY = {"day": "2015-10-09", "hr_min": 59, "hr_max": 135, "rhr": 61, "stress_avg": 30, "step_goal": 5070,
       "steps": 6219, "moderate_activity_time": "00:24:00.000000", "intensity_time_goal": "02:30:00.000000",
       "floors_up": 10.0, "floors_down": 5.55282, "floors_goal": 10.0, "distance": 4.788, "calories_total": 2238,
       "calories_bmr": 1976, "calories_active": 262, "hydration_goal": 2800, "rr_waking_avg": 14.0,
       "rr_max": 26.0, "rr_min": 11.0, "bb_charged": 47, "bb_max": 63, "bb_min": 13}
EMPTY_DAY = {"day": "2015-10-02", "intensity_time_goal": "02:30:00.000000", "hydration_goal": 2800}


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


NIGHT = ("2015-10-08", "2015-10-07 12:44:00.000000", "2015-10-07 18:42:00.000000", "05:49:00.000000",
         "01:18:00.000000", "03:06:00.000000", "01:25:00.000000", "00:09:00.000000", None, 14.0, 19.0, 75, "FAIR")
NO_SLEEP = ("2015-10-01", None, None, Z, Z, Z, Z, Z, None, None, None, None, None)

# Sessions as a watch's activity FIT files hold them: a gym Cardio session, whose
# zero distance means none measured; the Safety profile's walk, a sport the FIT SDK
# has no name for; and a ten-second walk, the first of a multisport file.
CARDIO = {"start_time": "2015-10-04T03:49:17+00:00", "sport": "training", "sub_sport": "cardio_training",
          "sport_profile_name": "Cardio", "total_elapsed_time": 2171.196, "total_timer_time": 2100.5,
          "total_distance": 0, "total_calories": 396, "avg_heart_rate": 163, "max_heart_rate": 194,
          "total_training_effect": 5.0, "total_anaerobic_training_effect": 2.9, "training_load_peak": 215.5}
SAFETY = {"start_time": "2014-01-06T16:16:51+00:00", "sport": 54, "sub_sport": 61, "total_elapsed_time": 2063.05,
          "total_distance": 2825.63, "total_ascent": 12, "total_descent": 11}
WALK = {"start_time": "2015-04-04T20:35:38+00:00", "sport": "walking", "sub_sport": "generic",
        "sport_profile_name": "Walk", "total_elapsed_time": 10.819, "total_distance": 2.52, "total_calories": 1}


def run(command, fit_dir, **config):
    db = Path(fit_dir).parent / "garmin.db"
    if not db.exists():
        garmin_db(db, [])
    activities = Path(fit_dir).parent / "Activities"
    activities.mkdir(exist_ok=True)
    request = {"command": command, "config": {"fit_dir": str(fit_dir), "activities_dir": str(activities),
                                              "garmin_db": str(db), "person_id": "person-a", **config}}
    out = subprocess.run([UV, "run", "-q", "--script", str(GARMIN)], input=json.dumps(request),
                         capture_output=True, text=True, check=True, timeout=120)
    return json.loads(out.stdout)


def payloads(r):
    return [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]


class ModuleTest(unittest.TestCase):
    """What the plugin decides without the FIT SDK, loaded as a module."""

    @classmethod
    def setUpClass(cls):
        import importlib.util

        spec = importlib.util.spec_from_file_location("garmin_run", GARMIN)
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)

    def test_a_file_gone_mid_run_is_retried_not_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            gone = Path(d) / "a_WELLNESS.fit"
            with self.assertRaises(self.mod.ductile.Failure) as ctx:
                self.mod.modified_since([gone], 0)
        self.assertTrue(ctx.exception.retry)
        self.assertIn("a_WELLNESS.fit went while the run read it", str(ctx.exception))

    def test_a_session_s_activity_name_is_google_fit_s_or_unknown(self):
        cases = [(("walking", "generic"), "walking"), (("walking", None), "walking"),
                 (("running", "treadmill"), "running.treadmill"), (("running", "trail"), "running"),
                 (("rowing", "indoor_rowing"), "rowing.machine"), (("training", "cardio_training"), "other"),
                 (("training", "strength_training"), "unknown"), (("54", "61"), "unknown"), ((None, None), "unknown")]
        for (sport, sub_sport), want in cases:
            with self.subTest(sport=sport, sub_sport=sub_sport):
                self.assertEqual(self.mod.activity_name(sport, sub_sport), want)

    def test_a_figure_the_watch_did_not_write_is_none(self):
        for v, want in [(float("nan"), None), (None, None), (True, None), ("3", None), (215.5, 215.5), (396.0, 396)]:
            with self.subTest(v=v):
                self.assertEqual(self.mod.measure(v), want)

    def test_the_local_day_s_zone_is_the_definitions_and_they_agree(self):
        # Alerts are UTC instants from the FIT file; the types keyed on a day share one zone,
        # and sleep's wall clock is read in it.
        zones = {json.loads((REPO / "garmin" / "definitions" / f"{t}.json").read_text())
                 ["meta"]["time_semantics"]["fact_time"]["zone"]
                 for t in ("garmin.day", "health.heart-rate-daily", "health.step-count")}
        self.assertEqual(zones, {str(self.mod.ZONE)})


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
            ["2015-09-25T11:31:00+00:00", 66, (117 << 8) | 100],
            ["2015-09-25T12:00:00+00:00", 22, 5],
        ])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [{"source": "garmin", "kind": "hr_high_alert", "fact_time": "2015-09-25T11:31:00Z",
                                        "heart_rate": 117, "threshold": 100, "unit": "bpm"}])
        self.assertIn("117", json.dumps(payloads(r)[0]))
        self.assertNotIn("117.0", json.dumps(payloads(r)[0]))

    def test_the_same_alert_in_two_files_is_sent_once(self):
        alert = ["2015-09-25T11:31:00+00:00", 66, (117 << 8) | 100]
        write_fit(self.dir / "a_WELLNESS.fit", [alert])
        write_fit(self.dir / "b_WELLNESS.fit", [alert, ["2015-09-26T08:00:00+00:00", 66, (121 << 8) | 100]])
        r = run("poll", self.dir)
        self.assertEqual([p["fact_time"] for p in payloads(r)], ["2015-09-25T11:31:00Z", "2015-09-26T08:00:00Z"])

    def test_poll_is_a_snapshot_and_handle_reads_only_recent_files(self):
        old = write_fit(self.dir / "old_WELLNESS.fit", [["2015-01-01T00:00:00+00:00", 66, (130 << 8) | 100]])
        write_fit(self.dir / "new_WELLNESS.fit", [["2015-09-25T11:31:00+00:00", 66, (117 << 8) | 100]])
        week_ago = time.time() - 7 * 86400
        os.utime(old, (week_ago, week_ago))
        polled = run("poll", self.dir)
        self.assertEqual(len(payloads(polled)), 2)
        self.assertEqual(polled["events"][0]["payload"]["snapshot"]["types"], ["exercise.session", "garmin.day", "health.heart-rate-alert", "health.heart-rate-daily", "health.step-count", "sleep.episode"])
        handled = run("handle", self.dir)
        self.assertEqual([p["heart_rate"] for p in payloads(handled)], [117])
        self.assertNotIn("snapshot", handled["events"][0]["payload"])

    def test_a_file_that_will_not_decode_is_logged_and_the_run_is_no_snapshot(self):
        write_fit(self.dir / "a_WELLNESS.fit", [["2015-09-25T11:31:00+00:00", 66, (117 << 8) | 100]])
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
            "id": "sleep:2015-10-08",
            # GarminDB's start and end are wall clock in the days' zone (Sydney, +11 that
            # October), not UTC as its column type suggests (anam card 174).
            "effective_time_frame": {"time_interval": {"start_date_time": "2015-10-07T01:44:00Z",
                                                       "end_date_time": "2015-10-07T07:42:00Z"}},
            "total_sleep_time": {"value": 349, "unit": "min"},
            "light_sleep_duration": {"value": 186, "unit": "min"},
            "deep_sleep_duration": {"value": 78, "unit": "min"},
            "rem_sleep_duration": {"value": 85, "unit": "min"},
            "wake_after_sleep_onset": {"value": 9, "unit": "min"},
            "is_main_sleep": True, "score": 75, "qualifier": "FAIR", "avg_rr": 14, "avg_stress": 19,
        }])
        self.assertEqual(r["events"][0]["payload"]["snapshot"]["types"], ["exercise.session", "garmin.day", "health.heart-rate-alert", "health.heart-rate-daily", "health.step-count", "sleep.episode"])

    def test_a_night_s_instants_are_the_zone_s_wall_clock_in_utc(self):
        # A night that began after local midnight, so the UTC instants fall on the
        # day before Garmin's day. Garmin's own GMT stamps for this night: 13:33Z
        # and 21:03Z. The id keeps Garmin's day.
        night = ("2026-10-17", "2026-10-17 00:33:00.000000", "2026-10-17 08:03:00.000000", "05:53:00.000000",
                 "00:54:00.000000", "03:49:00.000000", "01:10:00.000000", "01:37:00.000000", None, None, None, None, None)
        garmin_db(self.dir.parent / "garmin.db", [night])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        p = payloads(r)[0]
        self.assertEqual(p["id"], "sleep:2026-10-17")
        self.assertEqual(p["effective_time_frame"]["time_interval"],
                         {"start_date_time": "2026-10-16T13:33:00Z", "end_date_time": "2026-10-16T21:03:00Z"})

    def test_a_day_s_heart_rate_is_three_omh_figures_and_an_empty_one_is_none(self):
        garmin_db(self.dir.parent / "garmin.db", [], resting=[("2015-10-09", 61.0)],
                  daily=[("2015-10-09", 59, 135), ("2015-04-05", None, 120)])
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        sydney_day = {"time_interval": {"start_date_time": "2015-10-09T00:00:00+11:00",
                                        "end_date_time": "2015-10-10T00:00:00+11:00"}}
        self.assertEqual(payloads(r), [
            {"id": "2015-04-05", "statistic": "maximum", "heart_rate": {"value": 120, "unit": "beats/min"},
             "effective_time_frame": {"time_interval": {"start_date_time": "2015-04-05T00:00:00+11:00",
                                                        "end_date_time": "2015-04-06T00:00:00+10:00"}},
             "descriptive_statistic": "maximum"},
            {"id": "2015-10-09", "statistic": "resting", "heart_rate": {"value": 61, "unit": "beats/min"},
             "effective_time_frame": sydney_day, "temporal_relationship_to_physical_activity": "at rest"},
            {"id": "2015-10-09", "statistic": "minimum", "heart_rate": {"value": 59, "unit": "beats/min"},
             "effective_time_frame": sydney_day, "descriptive_statistic": "minimum"},
            {"id": "2015-10-09", "statistic": "maximum", "heart_rate": {"value": 135, "unit": "beats/min"},
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
            "id": "steps:2015-10-09", "step_count": {"value": 6219, "unit": "steps"},
            "effective_time_frame": {"time_interval": {"start_date_time": "2015-10-09T00:00:00+11:00",
                                                       "end_date_time": "2015-10-10T00:00:00+11:00"}}}])
        self.assertEqual(by_type["garmin.day"], [{
            "id": "day:2015-10-09", "day": "2015-10-09", "step_goal": 5070, "floors_up": 10, "floors_down": 5.55282, "floors_goal": 10,
            "calories_total": 2238, "calories_bmr": 1976, "calories_active": 262, "hydration_goal": 2800,
            "stress_avg": 30, "rr_waking_avg": 14, "rr_max": 26, "rr_min": 11, "bb_charged": 47, "bb_max": 63,
            "bb_min": 13, "distance_km": 4.788, "moderate_activity_minutes": 24, "vigorous_activity_minutes": 0,
            "intensity_time_goal_minutes": 150}])

    def test_a_session_is_the_ieee_body_at_its_utc_start_with_garmin_s_measures_beside_it(self):
        write_fit(self.dir.parent / "Activities" / "1_ACTIVITY.fit", {"sessions": [CARDIO]})
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [{
            "id": "garmin:session:2015-10-04T03:49:17Z", "activity_name": "other",
            "effective_time_frame": {"time_interval": {"start_date_time": "2015-10-04T03:49:17Z",
                                                       "duration": {"value": 2171.196, "unit": "sec"}}},
            "source": "Garmin", "fit_sport": "training", "fit_sub_sport": "cardio_training", "sport_profile": "Cardio",
            "duration": {"value": 2100.5, "unit": "sec"}, "kcal_burned": {"value": 396, "unit": "kcal"},
            "avg_hr_bpm": 163, "max_hr_bpm": 194, "training_effect_aerobic": 5, "training_effect_anaerobic": 2.9,
            "training_load": 215.5,
        }])

    def test_each_session_in_a_file_is_one_and_a_sport_the_sdk_cannot_name_is_unknown(self):
        write_fit(self.dir.parent / "Activities" / "2_ACTIVITY.fit", {"sessions": [WALK, SAFETY]})
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        got = {p["id"]: p for p in payloads(r)}
        self.assertEqual(list(got), ["garmin:session:2014-01-06T16:16:51Z", "garmin:session:2015-04-04T20:35:38Z"])
        self.assertEqual(got["garmin:session:2014-01-06T16:16:51Z"], {
            "id": "garmin:session:2014-01-06T16:16:51Z", "activity_name": "unknown",
            "effective_time_frame": {"time_interval": {"start_date_time": "2014-01-06T16:16:51Z",
                                                       "duration": {"value": 2063.05, "unit": "sec"}}},
            "source": "Garmin", "fit_sport": "54", "fit_sub_sport": "61",
            "distance": {"value": 2825.63, "unit": "m"}, "cumulative_elevation_gain": {"value": 12, "unit": "m"},
            "descent_m": 11})
        self.assertEqual(got["garmin:session:2015-04-04T20:35:38Z"]["activity_name"], "walking")

    def test_handle_reads_only_recent_activity_files(self):
        acts = self.dir.parent / "Activities"
        old = write_fit(acts / "1_ACTIVITY.fit", {"sessions": [SAFETY]})
        write_fit(acts / "2_ACTIVITY.fit", {"sessions": [CARDIO]})
        week_ago = time.time() - 7 * 86400
        os.utime(old, (week_ago, week_ago))
        self.assertEqual(len(payloads(run("poll", self.dir))), 2)
        self.assertEqual([p["id"] for p in payloads(run("handle", self.dir))], ["garmin:session:2015-10-04T03:49:17Z"])

    def test_an_activity_file_that_will_not_decode_is_logged_and_the_run_is_no_snapshot(self):
        acts = self.dir.parent / "Activities"
        write_fit(acts / "1_ACTIVITY.fit", {"sessions": [CARDIO]})
        acts.joinpath("2_ACTIVITY.fit").write_bytes(b"not a FIT file")
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(len(payloads(r)), 1)
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertTrue(any("2_ACTIVITY.fit" in line["message"] for line in r.get("logs", [])), r.get("logs"))

    def test_a_missing_fit_dir_is_not_retried(self):
        r = run("poll", self.dir / "nowhere")
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_every_type_is_admitted_and_a_resend_is_no_op(self):
        write_fit(self.dir / "a_WELLNESS.fit", [["2015-09-25T11:31:00+00:00", 66, (117 << 8) | 100],
                                                ["2015-09-26T08:00:00+00:00", 66, (121 << 8) | 100]])
        # The same date in sleep, steps, the day record and heart rate: five types under one
        # source, none of them one facet (anam card 55, identity across types).
        same_day = ("2015-10-09",) + NIGHT[1:]
        write_fit(self.dir.parent / "Activities" / "1_ACTIVITY.fit", {"sessions": [WALK, CARDIO]})
        garmin_db(self.dir.parent / "garmin.db", [NIGHT, same_day, NO_SLEEP], resting=[("2015-10-09", 61.0)],
                  daily=[DAY, EMPTY_DAY])
        daemon = Daemon("garmin", ["exercise.session", "garmin.day", "health.heart-rate-alert",
                                   "health.heart-rate-daily", "health.step-count", "sleep.episode"])
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
                self.assertEqual(got, [{want: 2}, {want: 2}, {want: 3}, {want: 1}, {want: 1}, {want: 2}])
        finally:
            daemon.close()


if __name__ == "__main__":
    unittest.main()
