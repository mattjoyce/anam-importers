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
from datetime import datetime, timedelta, timezone
from pathlib import Path

from anam_importer import Client
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


def summary(fit_dir: Path, day: str, start: str, end: str, steps=None) -> None:
    """Garmin Connect's daily summary for day as GarminDB keeps it, under fit_dir by
    year: start and end given as RFC 3339 with the watch's offset, written as Garmin
    writes them, each in GMT and on the watch's clock."""
    s, e = datetime.fromisoformat(start), datetime.fromisoformat(end)

    def gmt(t):
        return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.0")

    def local(t):
        return t.strftime("%Y-%m-%dT%H:%M:%S.0")

    path = fit_dir / day[:4] / f"daily_summary_{day}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"calendarDate": day, "wellnessStartTimeGmt": gmt(s), "wellnessStartTimeLocal": local(s),
                                "wellnessEndTimeGmt": gmt(e), "wellnessEndTimeLocal": local(e), "totalSteps": steps}))


def ms(t: str) -> int:
    """An RFC 3339 time as Garmin's GMT epoch in milliseconds."""
    return int(datetime.fromisoformat(t).timestamp() * 1000)


def sleep_json(sleep_dir: Path, day: str, start: str, end: str) -> None:
    """Garmin's sleep for day as GarminDB keeps it: each end a GMT epoch and the same
    moment on the watch's clock, both in milliseconds."""
    def local_ms(t):
        return ms(t) + int(datetime.fromisoformat(t).utcoffset().total_seconds() * 1000)

    sleep_dir.mkdir(parents=True, exist_ok=True)
    (sleep_dir / f"sleep_{day}.json").write_text(json.dumps({"dailySleepDTO": {
        "calendarDate": day, "sleepStartTimestampGMT": ms(start), "sleepStartTimestampLocal": local_ms(start),
        "sleepEndTimestampGMT": ms(end), "sleepEndTimestampLocal": local_ms(end)}}))


def source(value: str, zone: str = "UTC", basis: str = "source"):
    return {"value": value, "zone": zone, "basis": basis}


def day_of(start: str, end: str):
    return {"time_interval": {"start_date_time": start, "end_date_time": end}}


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
    sleep = Path(fit_dir).parent / "Sleep"
    sleep.mkdir(exist_ok=True)
    request = {"command": command, "config": {"fit_dir": str(fit_dir), "activities_dir": str(activities),
                                              "sleep_dir": str(sleep), "garmin_db": str(db), "person_id": "person-a",
                                              **config}}
    out = subprocess.run([UV, "run", "-q", "--script", str(GARMIN)], input=json.dumps(request),
                         capture_output=True, text=True, check=True, timeout=120)
    return json.loads(out.stdout)


def payloads(r):
    return [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]


def typed(r):
    out = {}
    for ev in r["events"]:
        for e in ev["payload"]["envelopes"]:
            out.setdefault(e["type"], []).append(e["payload"])
    return out


def logged(r):
    return [line["message"] for line in r.get("logs", [])]


# What a poll's snapshot speaks for: the seven types it sends, and health.heart-rate-day,
# which it sends no more, so Anam reports that type's live facts absent (anam card 205).
POLLED_TYPES = ["activity.day.garmin", "activity.exercise-session.garmin", "activity.steps", "health.heart-rate-alert",
                "health.heart-rate-day", "health.heart-rate.day", "health.heart-rate.hour", "health.sleep-episode"]
# GARMIN_TYPES are what the garmin principal lists in the daemon's importers file.
GARMIN_TYPES = POLLED_TYPES


def bpm(v):
    return {"value": v, "unit": "beats/min"}


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
        # Alerts and sessions are UTC instants from the FIT file and nights are Garmin's GMT
        # epochs; the types keyed on a day share one zone, which a day Garmin gave no interval
        # for is read in.
        zones = {json.loads((REPO / "garmin" / "definitions" / f"{t}.json").read_text())
                 ["meta"]["time_semantics"]["fact_time"]["zone"]
                 for t in ("activity.day.garmin", "health.heart-rate.day", "activity.steps")}
        self.assertEqual(zones, {self.mod.ZONE})

    def frame(self, day, start, end, steps=None, given=None):
        with tempfile.TemporaryDirectory() as d:
            summary(Path(d), day, start, end, steps)
            return self.mod.summary_frame(Path(d), day, given)

    def test_a_sydney_day_keeps_the_interval_garmin_counted(self):
        # Acceptance example 2: Garmin's 20 October in Sydney is Sydney's day, offsets and all.
        # A client in London places it by these instants, not by its own 20 October.
        f = self.frame("2026-10-20", "2026-10-20T00:00:00+11:00", "2026-10-21T00:00:00+11:00")
        self.assertEqual(f.frame, day_of("2026-10-20T00:00:00+11:00", "2026-10-21T00:00:00+11:00"))
        self.assertEqual(f.source_time, source("2026-10-20", "+11:00"))

    def test_a_day_follows_the_watch_across_a_flight(self):
        # The live days of Matt's flight to London: Garmin's 17 October began in Sydney and ended
        # in London, 34 hours later, and the 18th is London's.
        cases = [("2026-10-16", "2026-10-16T00:00:00+11:00", "2026-10-17T00:00:00+11:00", "+11:00", 24),
                 ("2026-10-17", "2026-10-17T00:00:00+11:00", "2026-10-18T00:00:00+01:00", "+11:00", 34),
                 ("2026-10-18", "2026-10-18T00:00:00+01:00", "2026-10-19T00:00:00+01:00", "+01:00", 24)]
        for day, start, end, zone, hours in cases:
            with self.subTest(day=day):
                f = self.frame(day, start, end)
                self.assertEqual(f.frame, day_of(start, end))
                self.assertEqual(f.source_time, source(day, zone))
                span = datetime.fromisoformat(end) - datetime.fromisoformat(start)
                self.assertEqual(span.total_seconds(), hours * 3600)

    def test_a_day_the_clocks_change_in_is_as_long_as_garmin_counted(self):
        # Acceptance example 4, from the source: Sydney's clocks went forward on 4 October 2026,
        # London's go back on 25 October. Garmin gives both offsets; nothing is guessed.
        for day, start, end, hours in [("2026-10-04", "2026-10-04T00:00:00+10:00", "2026-10-05T00:00:00+11:00", 23),
                                       ("2026-10-25", "2026-10-25T00:00:00+01:00", "2026-10-26T00:00:00+00:00", 25)]:
            with self.subTest(day=day):
                f = self.frame(day, start, end)
                self.assertEqual(f.frame, day_of(start, end))
                span = datetime.fromisoformat(end) - datetime.fromisoformat(start)
                self.assertEqual(span.total_seconds(), hours * 3600)

    def test_a_day_still_in_progress_ends_where_garmin_had_counted_to(self):
        f = self.frame("2026-10-20", "2026-10-20T00:00:00+01:00", "2026-10-20T15:20:00+01:00")
        self.assertEqual(f.frame, day_of("2026-10-20T00:00:00+01:00", "2026-10-20T15:20:00+01:00"))

    def test_a_day_garmin_gave_no_interval_for_is_assumed_and_says_so(self):
        # Acceptance example 3: a bare date read in the Definition's zone is an assumption, and
        # the record says so. Example 4: on a day Sydney's clocks change, midnight still exists
        # once, so the assumed day is 23 or 25 hours.
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(self.mod.summary_frame(Path(d), "2026-10-04"))
        for day, start, end in [("2026-10-04", "2026-10-04T00:00:00+10:00", "2026-10-05T00:00:00+11:00"),
                                ("2026-04-05", "2026-04-05T00:00:00+11:00", "2026-04-06T00:00:00+10:00")]:
            with self.subTest(day=day):
                f = self.mod.assumed_frame(day)
                self.assertEqual(f.frame, day_of(start, end))
                self.assertEqual(f.source_time, source(day, "Australia/Sydney", "assumption"))

    def test_a_summary_that_disagrees_with_garmin_db_is_refused(self):
        with self.assertRaisesRegex(ValueError, "counts 100 steps and garmin.db 120"):
            self.frame("2026-10-18", "2026-10-18T00:00:00+01:00", "2026-10-19T00:00:00+01:00", steps=100, given=120)
        with self.assertRaisesRegex(ValueError, "is not day 2026-10-18's"):
            self.frame("2026-10-18", "2026-10-17T00:00:00+01:00", "2026-10-18T00:00:00+01:00")
        with self.assertRaisesRegex(ValueError, "no zone's offset"):
            with tempfile.TemporaryDirectory() as d:
                summary(Path(d), "2026-10-18", "2026-10-18T00:00:00+01:00", "2026-10-19T00:00:00+01:00")
                path = Path(d) / "2026" / "daily_summary_2026-10-18.json"
                body = json.loads(path.read_text())
                body["wellnessStartTimeLocal"] = "2026-10-18T00:00:30.0"
                body["wellnessStartTimeGmt"] = "2026-10-17T23:00:00.0"
                path.write_text(json.dumps(body))
                self.mod.summary_frame(Path(d), "2026-10-18")

    def test_a_night_is_garmin_s_instants_on_the_watch_s_clock(self):
        # Acceptance example 1: a start supplied as 20:00 at +11:00 is 09:00 UTC, and keeps the
        # value Garmin wrote and how it was read.
        with tempfile.TemporaryDirectory() as d:
            sleep_json(Path(d), "2026-10-21", "2026-10-20T20:00:00+11:00", "2026-10-21T06:00:00+11:00")
            f = self.mod.sleep_frame(Path(d), "2026-10-21")
        start = f.frame["time_interval"]["start_date_time"]
        self.assertEqual(start, "2026-10-20T20:00:00+11:00")
        self.assertEqual(datetime.fromisoformat(start).astimezone(timezone.utc),
                         datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc))
        self.assertEqual(f.source_time, source(str(ms("2026-10-20T09:00:00+00:00"))))

    def test_a_short_timestamp_names_the_instant_nearest_the_last_full_one(self):
        # A monitoring message may carry 16 bits of its timestamp, the FIT epoch's seconds
        # modulo 65536, which the SDK leaves unresolved: the nearest such instant to the
        # file's last full timestamp is the one meant.
        epoch = self.mod.FIT_EPOCH
        anchor = datetime(2026, 10, 11, 3, 2, tzinfo=timezone.utc)
        at = int((anchor - epoch).total_seconds())
        for delta in (-3600, -2, 0, 60, 3599):
            with self.subTest(delta=delta):
                self.assertEqual(self.mod.short_instant(anchor, (at + delta) % 65536),
                                 anchor + timedelta(seconds=delta))
        wrap = epoch + timedelta(seconds=65530)
        self.assertEqual(self.mod.short_instant(wrap, 4), epoch + timedelta(seconds=65540))
        self.assertEqual(self.mod.short_instant(wrap, 65535), epoch + timedelta(seconds=65535))

    def test_a_sample_needs_an_instant_and_a_heart_rate(self):
        # The watch writes zero for a heart rate it did not take, and an invalid byte the
        # SDK reads as none; a sample with no instant this can place is counted, not
        # shaped into the wrong hour.
        at = datetime(2026, 10, 11, 3, 2, tzinfo=timezone.utc)
        held = self.mod.scan({"monitoring_mesgs": [
            {"timestamp": at, "heart_rate": 54},
            {"timestamp": at + timedelta(minutes=1), "heart_rate": 0},
            {"timestamp": at + timedelta(minutes=2), "heart_rate": None},
            {"timestamp_16": 3600, "heart_rate": 55},
            {"heart_rate": 60},
        ]})
        self.assertEqual(held.beats, [self.mod.Beats(at, 54),
                                      self.mod.Beats(self.mod.short_instant(at, 3600), 55)])
        self.assertEqual(held.unplaced, 1)
        self.assertEqual(held.alerts, [])

    def test_an_hour_has_a_slot_a_minute_and_a_minute_with_no_sample_is_null(self):
        at = datetime(2026, 10, 11, 3, tzinfo=timezone.utc)
        got = self.mod.hour_payloads([self.mod.Beats(at, 54),
                                      self.mod.Beats(at + timedelta(minutes=1, seconds=30), 55),
                                      self.mod.Beats(at + timedelta(minutes=59), 60)])
        self.assertEqual(got, [{
            "id": "2026-10-11T03:00:00Z",
            "bpm": [54, 55] + [None] * 57 + [60],
            "unit": "beats/min",
            "effective_time_frame": {"time_interval": {
                "start_date_time": "2026-10-11T03:00:00Z", "end_date_time": "2026-10-11T04:00:00Z"}},
            "source_time": source("2026-10-11T03:00:00Z")}])

    def test_a_minute_s_last_sample_is_its_slot_and_one_facet_is_one_utc_hour(self):
        at = datetime(2026, 10, 11, 3, 7, 10, tzinfo=timezone.utc)
        got = self.mod.hour_payloads([self.mod.Beats(at, 54),
                                      self.mod.Beats(at + timedelta(seconds=25), 57),
                                      self.mod.Beats(at + timedelta(hours=1), 62),
                                      self.mod.Beats(at + timedelta(hours=1), 62)])
        self.assertEqual([p["id"] for p in got], ["2026-10-11T03:00:00Z", "2026-10-11T04:00:00Z"])
        self.assertEqual(got[0]["bpm"][7], 57)
        self.assertEqual(sum(v is not None for v in got[0]["bpm"]), 1)
        self.assertEqual(got[1]["bpm"][7], 62)
        self.assertEqual(sum(v is not None for v in got[1]["bpm"]), 1)


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
                                        "heart_rate": 117, "threshold": 100, "unit": "bpm",
                                        "source_time": source("2015-09-25T11:31:00Z")}])
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
        self.assertEqual(polled["events"][0]["payload"]["snapshot"]["types"], POLLED_TYPES)
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

    def test_an_hour_is_one_facet_of_sixty_slots_and_a_gap_is_null(self):
        write_fit(self.dir / "a_WELLNESS.fit", {"monitoring": [
            {"timestamp": "2026-10-11T03:00:00+00:00", "heart_rate": 54},
            {"timestamp": "2026-10-11T03:01:10+00:00", "heart_rate": 55},
            {"timestamp": "2026-10-11T03:04:00+00:00", "heart_rate": 58},
            {"timestamp": "2026-10-11T04:00:00+00:00", "heart_rate": 62},
        ]})
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(typed(r), {"health.heart-rate.hour": [
            {"id": "2026-10-11T03:00:00Z", "bpm": [54, 55, None, None, 58] + [None] * 55, "unit": "beats/min",
             "effective_time_frame": day_of("2026-10-11T03:00:00Z", "2026-10-11T04:00:00Z"),
             "source_time": source("2026-10-11T03:00:00Z")},
            {"id": "2026-10-11T04:00:00Z", "bpm": [62] + [None] * 59, "unit": "beats/min",
             "effective_time_frame": day_of("2026-10-11T04:00:00Z", "2026-10-11T05:00:00Z"),
             "source_time": source("2026-10-11T04:00:00Z")},
        ]})
        self.assertEqual(r["events"][0]["payload"]["snapshot"]["types"], POLLED_TYPES)

    def test_the_hours_of_a_day_the_clocks_change_are_utc_s(self):
        # Sydney's clocks went back on 5 April 2026 and forward on 4 October; London's went
        # back on 25 October. A FIT timestamp is UTC by the format's definition, so each of
        # those days is 24 hours of 24 facets, their boundaries unmoved.
        for day in ("2026-04-05", "2026-10-04", "2026-10-25"):
            with self.subTest(day=day):
                d = self.dir / day
                write_fit(d / f"{day}_WELLNESS.fit", {"monitoring": [
                    {"timestamp": f"{day}T{hour:02d}:{minute:02d}:00+00:00", "heart_rate": 60}
                    for hour in range(24) for minute in (0, 30)]})
                r = run("poll", d)
                self.assertEqual(r["status"], "ok", r)
                got = typed(r)["health.heart-rate.hour"]
                self.assertEqual([p["id"] for p in got], [f"{day}T{hour:02d}:00:00Z" for hour in range(24)])
                self.assertEqual({sum(v is not None for v in p["bpm"]) for p in got}, {2})

    def test_an_hour_that_gains_a_sample_is_sent_again_with_it(self):
        # Same-day fetching (anam card 128) means the watch's file is read again while the
        # hour is still going: an hour that gains a sample is a new payload, and the one
        # before it is what Anam holds until then.
        path = self.dir / "a_WELLNESS.fit"
        write_fit(path, {"monitoring": [{"timestamp": "2026-10-11T03:00:00+00:00", "heart_rate": 54}]})
        first = typed(run("poll", self.dir))["health.heart-rate.hour"]
        write_fit(path, {"monitoring": [{"timestamp": "2026-10-11T03:00:00+00:00", "heart_rate": 54},
                                        {"timestamp": "2026-10-11T03:00:40+00:00", "heart_rate": 59}]})
        again = typed(run("poll", self.dir))["health.heart-rate.hour"]
        self.assertEqual(first[0]["bpm"][0], 54)
        self.assertEqual(again[0]["bpm"][0], 59)
        self.assertNotEqual(first, again)

    def test_a_sample_that_cannot_be_placed_is_logged_and_the_run_is_no_snapshot(self):
        write_fit(self.dir / "a_WELLNESS.fit", {"monitoring": [
            {"timestamp_16": 3600, "heart_rate": 55},
            {"timestamp": "2026-10-11T03:00:00+00:00", "heart_rate": 54},
            {"heart_rate": 60},
        ]})
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual([p["id"] for p in typed(r)["health.heart-rate.hour"]], ["2026-10-11T03:00:00Z"])
        self.assertTrue(any("a_WELLNESS.fit: no full timestamp" in m for m in logged(r)), logged(r))
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertEqual(run("health", self.dir)["status"], "error")

    def test_a_night_is_the_ieee_body_with_garmin_s_fields_beside_it(self):
        garmin_db(self.dir.parent / "garmin.db", [NIGHT, NO_SLEEP])
        # GarminDB's start and end are wall clock in its own zone (anam card 174); the night is
        # timed by Garmin's sleep JSON instead, its GMT epochs on the watch's clock.
        sleep_json(self.dir.parent / "Sleep", "2015-10-08", "2015-10-07T12:44:00+11:00", "2015-10-07T18:42:00+11:00")
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [{
            "id": "sleep:2015-10-08",
            "effective_time_frame": {"time_interval": {"start_date_time": "2015-10-07T12:44:00+11:00",
                                                       "end_date_time": "2015-10-07T18:42:00+11:00"}},
            "source_time": source(str(ms("2015-10-07T01:44:00+00:00"))),
            "total_sleep_time": {"value": 349, "unit": "min"},
            "light_sleep_duration": {"value": 186, "unit": "min"},
            "deep_sleep_duration": {"value": 78, "unit": "min"},
            "rem_sleep_duration": {"value": 85, "unit": "min"},
            "wake_after_sleep_onset": {"value": 9, "unit": "min"},
            "is_main_sleep": True, "score": 75, "qualifier": "FAIR", "avg_rr": 14, "avg_stress": 19,
        }])
        self.assertEqual(r["events"][0]["payload"]["snapshot"]["types"], POLLED_TYPES)

    def test_a_london_night_is_london_s_whatever_zone_garmin_db_runs_in(self):
        # A night in London: garmin.db holds it as Sydney wall clock, the zone GarminDB runs
        # in, and Garmin's JSON as GMT epochs with the watch's +01:00 beside them. The JSON
        # decides. A night with no JSON is left out, logged, and the run is no snapshot.
        london = ("2026-10-18", "2026-10-18 07:44:00.000000", "2026-10-18 17:06:00.000000", "08:20:00.000000",
                  "01:00:00.000000", "05:00:00.000000", "02:00:00.000000", "00:20:00.000000", None, None, None, None, None)
        untimed = ("2026-10-19",) + london[1:]
        garmin_db(self.dir.parent / "garmin.db", [london, untimed])
        sleep_json(self.dir.parent / "Sleep", "2026-10-18", "2026-10-17T21:44:00+01:00", "2026-10-18T07:06:00+01:00")
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual([p["id"] for p in payloads(r)], ["sleep:2026-10-18"])
        self.assertEqual(payloads(r)[0]["effective_time_frame"],
                         day_of("2026-10-17T21:44:00+01:00", "2026-10-18T07:06:00+01:00"))
        self.assertEqual(payloads(r)[0]["source_time"], source(str(ms("2026-10-17T20:44:00+00:00"))))
        self.assertTrue(any("skipped night 2026-10-19" in m for m in logged(r)), logged(r))
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertEqual(run("health", self.dir)["status"], "error")

    def test_a_day_s_heart_rate_is_one_fact_and_a_figure_garmin_left_empty_is_no_field(self):
        # Anam card 205: resting, minimum and maximum are one health.heart-rate.day. 5 April
        # has a maximum only and no interval from Garmin, the day Sydney's clocks went back,
        # so it is assumed, 25 hours of Sydney. 18 February 2026 is the live day with a resting
        # figure only and no summary: resting_hr holds it and daily_summary does not. Both
        # say they were assumed, and the run is still everything.
        garmin_db(self.dir.parent / "garmin.db", [], resting=[("2015-10-09", 61.0), ("2026-02-18", 59.0)],
                  daily=[("2015-10-09", 59, 135), ("2015-04-05", None, 120), ("2015-04-06", None, None)])
        summary(self.dir, "2015-10-09", "2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00")
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [
            {"id": "2015-04-05", "maximum": bpm(120),
             "effective_time_frame": day_of("2015-04-05T00:00:00+11:00", "2015-04-06T00:00:00+10:00"),
             "source_time": source("2015-04-05", "Australia/Sydney", "assumption")},
            {"id": "2015-10-09", "resting": bpm(61), "minimum": bpm(59), "maximum": bpm(135),
             "effective_time_frame": day_of("2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00"),
             "source_time": source("2015-10-09", "+11:00")},
            {"id": "2026-02-18", "resting": bpm(59),
             "effective_time_frame": day_of("2026-02-18T00:00:00+11:00", "2026-02-19T00:00:00+11:00"),
             "source_time": source("2026-02-18", "Australia/Sydney", "assumption")},
        ])
        self.assertEqual({e["type"] for ev in r["events"] for e in ev["payload"]["envelopes"]}, {"health.heart-rate.day"})
        for day in ("2015-04-05", "2026-02-18"):
            self.assertTrue(any(f"day {day}: Garmin gave no interval" in m for m in logged(r)), logged(r))
        self.assertEqual(r["events"][0]["payload"]["snapshot"]["types"], POLLED_TYPES)

    def test_a_day_is_omh_steps_and_garmin_s_record_and_an_empty_day_is_neither(self):
        garmin_db(self.dir.parent / "garmin.db", [], daily=[DAY, EMPTY_DAY])
        summary(self.dir, "2015-10-09", "2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00", steps=6219)
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        by_type = typed(r)
        frame = day_of("2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00")
        self.assertEqual(by_type["activity.steps"], [{
            "id": "steps:2015-10-09", "step_count": {"value": 6219, "unit": "steps"},
            "effective_time_frame": frame, "source_time": source("2015-10-09", "+11:00")}])
        self.assertEqual(by_type["activity.day.garmin"], [{
            "id": "day:2015-10-09", "day": "2015-10-09", "step_goal": 5070, "floors_up": 10, "floors_down": 5.55282, "floors_goal": 10,
            "calories_total": 2238, "calories_bmr": 1976, "calories_active": 262, "hydration_goal": 2800,
            "stress_avg": 30, "rr_waking_avg": 14, "rr_max": 26, "rr_min": 11, "bb_charged": 47, "bb_max": 63,
            "bb_min": 13, "distance_km": 4.788, "moderate_activity_minutes": 24, "vigorous_activity_minutes": 0,
            "intensity_time_goal_minutes": 150, "effective_time_frame": frame,
            "source_time": source("2015-10-09", "+11:00")}])

    def test_a_london_day_is_london_s_and_a_summary_not_yet_imported_waits(self):
        # Since 18 October 2026 the watch's days are London's. A summary whose steps are not
        # garmin.db's is one GarminDB has not imported yet: that day waits for the next sync,
        # logged, and the run is no snapshot.
        london = dict(DAY, day="2026-10-18", steps=3834)
        behind = dict(DAY, day="2026-10-19", steps=6128)
        garmin_db(self.dir.parent / "garmin.db", [], daily=[london, behind])
        summary(self.dir, "2026-10-18", "2026-10-18T00:00:00+01:00", "2026-10-19T00:00:00+01:00", steps=3834)
        summary(self.dir, "2026-10-19", "2026-10-19T00:00:00+01:00", "2026-10-20T00:00:00+01:00", steps=6000)
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        by_type = typed(r)
        self.assertEqual([p["id"] for p in by_type["activity.steps"]], ["steps:2026-10-18"])
        self.assertEqual(by_type["activity.steps"][0]["effective_time_frame"],
                         day_of("2026-10-18T00:00:00+01:00", "2026-10-19T00:00:00+01:00"))
        self.assertEqual(by_type["activity.day.garmin"][0]["source_time"], source("2026-10-18", "+01:00"))
        self.assertTrue(any("skipped day 2026-10-19" in m for m in logged(r)), logged(r))
        self.assertNotIn("snapshot", r["events"][0]["payload"])

    def test_a_session_is_the_ieee_body_at_its_utc_start_with_garmin_s_measures_beside_it(self):
        write_fit(self.dir.parent / "Activities" / "1_ACTIVITY.fit", {"sessions": [CARDIO]})
        r = run("poll", self.dir)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(payloads(r), [{
            "id": "garmin:session:2015-10-04T03:49:17Z", "activity_name": "other",
            "effective_time_frame": {"time_interval": {"start_date_time": "2015-10-04T03:49:17Z",
                                                       "duration": {"value": 2171.196, "unit": "sec"}}},
            "source": "Garmin", "source_time": source("2015-10-04T03:49:17Z"),
            "fit_sport": "training", "fit_sub_sport": "cardio_training", "sport_profile": "Cardio",
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
            "source": "Garmin", "source_time": source("2014-01-06T16:16:51Z"), "fit_sport": "54", "fit_sub_sport": "61",
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
        write_fit(self.dir / "a_WELLNESS.fit", {
            "events": [["2015-09-25T11:31:00+00:00", 66, (117 << 8) | 100],
                       ["2015-09-26T08:00:00+00:00", 66, (121 << 8) | 100]],
            "monitoring": [{"timestamp": "2015-09-25T11:32:00+00:00", "heart_rate": 80},
                           {"timestamp": "2015-09-25T11:33:00+00:00", "heart_rate": 82}]})
        # The same date in sleep, steps, the day record, heart rate and an hour of it: six
        # types under one source, none of them one facet (anam card 55, identity across types).
        same_day = ("2015-10-09",) + NIGHT[1:]
        write_fit(self.dir.parent / "Activities" / "1_ACTIVITY.fit", {"sessions": [WALK, CARDIO]})
        garmin_db(self.dir.parent / "garmin.db", [NIGHT, same_day, NO_SLEEP], resting=[("2015-10-09", 61.0)],
                  daily=[DAY, EMPTY_DAY])
        summary(self.dir, "2015-10-09", "2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00", steps=6219)
        for day in ("2015-10-08", "2015-10-09"):
            sleep_json(self.dir.parent / "Sleep", day, "2015-10-07T12:44:00+11:00", "2015-10-07T18:42:00+11:00")
        daemon = Daemon("garmin", GARMIN_TYPES)
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
                self.assertEqual(got, [{want: 2}, {want: 1}, {want: 2}, {want: 1}, {want: 1}, {want: 1}, {want: 2}])
        finally:
            daemon.close()

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_an_hour_that_gains_a_sample_supersedes_and_a_resend_is_no_op(self):
        # The hour is read again while it is still going, so the same facet comes back
        # with a slot filled: a new version, not a second facet. Unchanged, it is what
        # Anam holds already and the batch admits nothing.
        path = self.dir / "a_WELLNESS.fit"

        def poll_and_submit():
            outcomes = []
            for ev in run("poll", self.dir)["events"]:
                r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                        "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                        "secrets": {"anam_importer_token_test": daemon.token}})
                self.assertEqual(r["status"], "ok", r)
                outcomes.append(r["events"][0]["payload"]["outcomes"])
            return outcomes

        write_fit(path, {"monitoring": [{"timestamp": "2026-10-11T03:00:00+00:00", "heart_rate": 54}]})
        daemon = Daemon("garmin", GARMIN_TYPES)
        try:
            self.assertEqual(poll_and_submit(), [{"admitted": 1}])
            write_fit(path, {"monitoring": [{"timestamp": "2026-10-11T03:00:00+00:00", "heart_rate": 54},
                                            {"timestamp": "2026-10-11T03:00:40+00:00", "heart_rate": 59}]})
            self.assertEqual(poll_and_submit(), [{"superseded": 1}])
            self.assertEqual(poll_and_submit(), [{"no-op": 1}])
        finally:
            daemon.close()

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_a_poll_leaves_the_old_figures_absent_and_retract_tombstones_them(self):
        # Anam card 205, by the normal reconciliation: before it the importer sent three
        # health.heart-rate-day facts a day. The new poll sends one health.heart-rate.day
        # a day and its snapshot names the old type too, so every old fact is absent,
        # and anam retract garmin tombstones those and nothing else.
        garmin_db(self.dir.parent / "garmin.db", [], resting=[("2015-10-09", 61.0), ("2015-10-10", 60.0)],
                  daily=[("2015-10-09", 59, 135), ("2015-10-10", 58, 140)])
        frames = {}
        for day, end in (("2015-10-09", "2015-10-10"), ("2015-10-10", "2015-10-11")):
            summary(self.dir, day, f"{day}T00:00:00+11:00", f"{end}T00:00:00+11:00")
            frames[day] = day_of(f"{day}T00:00:00+11:00", f"{end}T00:00:00+11:00")
        figures = {"2015-10-09": (61, 59, 135), "2015-10-10": (60, 58, 140)}
        old = []
        for day, (resting, low, high) in figures.items():
            common = {"id": day, "effective_time_frame": frames[day], "source_time": source(day, "+11:00")}
            old += [{**common, "statistic": "resting", "heart_rate": bpm(resting),
                     "temporal_relationship_to_physical_activity": "at rest"},
                    {**common, "statistic": "minimum", "heart_rate": bpm(low), "descriptive_statistic": "minimum"},
                    {**common, "statistic": "maximum", "heart_rate": bpm(high), "descriptive_statistic": "maximum"}]
        daemon = Daemon("garmin", GARMIN_TYPES)
        try:
            client = Client(daemon.url, daemon.token)
            sent = client.submit([{"type": "health.heart-rate-day", "definition_version": 2, "payload": p} for p in old])
            self.assertEqual(sent["changed"], 6)

            results = [run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                           "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                           "secrets": {"anam_importer_token_test": daemon.token}})
                       for ev in run("poll", self.dir)["events"]]
            self.assertTrue(all(r["status"] == "ok" for r in results), results)
            alerts = [e["payload"] for r in results for e in r["events"] if e["type"] == "anam.snapshot_absent"]
            self.assertEqual([(a["absent"], a["live"], a["carried"], a["types"]) for a in alerts],
                             [(6, 8, 2, POLLED_TYPES)])

            daemon.stop()
            dry = daemon.cli("retract", "garmin", "--max-fraction", "0.75")
            self.assertEqual(dry.returncode, 0, dry.stderr)
            self.assertIn("garmin: 8 live facets in the ledger, 2 rows in the source, 6 no longer held", dry.stdout)
            self.assertEqual(dry.stdout.count("  health.heart-rate-day  v"), 6, dry.stdout)
            done = daemon.cli("retract", "garmin", "--max-fraction", "0.75", "--yes")
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("tombstoned 6 facets", done.stdout)
            again = daemon.cli("retract", "garmin", "--max-fraction", "0.75")
            self.assertIn("2 live facets in the ledger, 2 rows in the source, 0 no longer held", again.stdout, again.stderr)
            daemon.start()

            status, coverage = client._call("GET", "/v1/coverage")
            self.assertEqual(status, 200, coverage)
            live = {t["type"]: t["count"] for t in coverage["types"]}
            self.assertEqual(live, {"health.heart-rate.day": 2})
        finally:
            daemon.close()


if __name__ == "__main__":
    unittest.main()
