"""anam_concept2: the Logbook's results, fetched into a cache under a personal token
and shaped as activity.exercise-session. The Logbook is stood in for by a local HTTP server
serving synthetic results; the daemon, when ANAM_BIN names one, is real."""

import http.server
import json
import os
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

CONCEPT2 = REPO / "concept2" / "run.py"
SUBMIT = REPO / "anam_submit" / "run.py"
TOKEN = "test-personal-token"

# Results as the Logbook lists them, synthetic. ROW is a JustRow ErgData synced, with
# splits and strokes; INTERVALS a fixed-distance interval workout; WEB one entered by
# hand on the website, totals only, no date_utc and a date at midnight.
ROW = {"id": 1001, "user_id": 7, "date": "2026-10-04 15:21:00", "timezone": "Australia/Sydney",
       "date_utc": "2026-10-04 04:21:00", "distance": 2000, "type": "rower", "time": 4800, "time_formatted": "8:00.0",
       "workout_type": "JustRow", "source": "ErgData Android", "weight_class": "H", "verified": True, "ranked": False,
       "comments": None, "privacy": "partners", "stroke_data": True, "calories_total": 120, "wattminutes_total": 1200,
       "drag_factor": 110, "stroke_count": 180, "stroke_rate": 22,
       "heart_rate": {"average": 150, "min": 0, "max": 0, "ending": 155, "recovery": 0},
       "workout": {"splits": [
           {"time": 2400, "distance": 1000, "calories_total": 60, "wattminutes_total": 600, "stroke_rate": 22,
            "heart_rate": {"average": 140, "min": 100, "max": 150, "ending": 150, "recovery": 0, "rest": 0}},
           {"time": 2400, "distance": 1000, "calories_total": 60, "wattminutes_total": 600, "stroke_rate": 22,
            "heart_rate": {"average": 158, "min": 150, "max": 165, "ending": 155, "recovery": 0, "rest": 0}}]},
       "real_time": None}
ROW_STROKES = [{"t": 25, "d": 60, "p": 2100, "spm": 20, "hr": 0}, {"t": 51, "d": 125, "p": 1950, "spm": 23, "hr": 102}]
INTERVALS = {"id": 1002, "user_id": 7, "date": "2026-09-13 11:39:00", "timezone": "Australia/Sydney",
             "date_utc": "2026-09-13 01:39:00", "distance": 500, "type": "rower", "time": 1400,
             "time_formatted": "2:20.0", "workout_type": "FixedDistanceInterval", "source": "ErgData Android",
             "weight_class": "H", "verified": True, "ranked": False, "comments": "one piece", "privacy": "partners",
             "stroke_data": False, "calories_total": 30, "stroke_rate": 24, "rest_time": 1200, "rest_distance": 200,
             "heart_rate": {"average": 145, "min": 0, "max": 0, "ending": 160, "recovery": 0},
             "workout": {"intervals": [
                 {"type": "distance", "time": 1400, "distance": 500, "calories_total": 30, "stroke_rate": 24, "rest_time": 1200,
                  "heart_rate": {"average": 145, "min": 105, "max": 162, "ending": 160, "recovery": 0, "rest": 140}}],
                 "targets": {"heart_rate_zone": 0}}, "real_time": None}
WEB = {"id": 1000, "user_id": 7, "date": "2021-01-15 00:00:00", "timezone": None, "date_utc": None, "distance": 5000,
       "type": "rower", "time": 13000, "time_formatted": "21:40.0", "workout_type": "unknown", "source": "Web",
       "weight_class": "H", "verified": False, "ranked": False, "comments": None, "privacy": "partners",
       "stroke_data": False, "real_time": None}


class Logbook:
    """A stand-in for log.concept2.com: pages of results and each result's strokes,
    under one bearer token. redirect_to makes every answer a redirect."""

    def __init__(self, results, strokes, per_page=250):
        self.results, self.strokes, self.per_page = list(results), dict(strokes), per_page
        self.requests = []
        self.redirect_to = None
        self.status = 200
        stand_in = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                stand_in.requests.append(self.path)
                if stand_in.redirect_to:
                    self.send_response(302)
                    self.send_header("Location", stand_in.redirect_to)
                    self.end_headers()
                    return
                if self.headers.get("Authorization") != "Bearer " + TOKEN:
                    return self.answer(401, {"message": "Unauthenticated."})
                if stand_in.status != 200:
                    return self.answer(stand_in.status, {"message": "no"})
                url = urllib.parse.urlsplit(self.path)
                parts = url.path.strip("/").split("/")
                if parts[:3] == ["api", "users", "me"] and parts[3:] == ["results"]:
                    q = urllib.parse.parse_qs(url.query)
                    page = int(q.get("page", ["1"])[0])
                    n = stand_in.per_page
                    pages = max(1, -(-len(stand_in.results) // n))
                    data = stand_in.results[(page - 1) * n: page * n]
                    return self.answer(200, {"data": data, "meta": {"pagination": {
                        "total": len(stand_in.results), "count": len(data), "per_page": n,
                        "current_page": page, "total_pages": pages, "links": []}}})
                if parts[:4] == ["api", "users", "me", "results"] and len(parts) == 6 and parts[5] == "strokes":
                    return self.answer(200, {"data": stand_in.strokes.get(int(parts[4]), [])})
                self.answer(404, {"message": "no"})

            def answer(self, status, body):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def payloads(r):
    return [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]


class ConceptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "concept2"
        self.cache.mkdir()
        self.logbook = Logbook([ROW, INTERVALS, WEB], {1001: ROW_STROKES})

    def tearDown(self):
        self.logbook.close()
        self.tmp.cleanup()

    def run_cmd(self, command, token=TOKEN, **config):
        request = {"command": command,
                   "config": {"cache_dir": str(self.cache), "person_id": "person-a", "token_secret": "concept2_token",
                              "logbook_url": self.logbook.url, **config}}
        if token is not None:
            request["secrets"] = {"concept2_token": token}
        return run_plugin(CONCEPT2, request)

    def test_fetch_caches_every_result_with_its_strokes_and_a_second_fetch_fetches_nothing(self):
        r = self.run_cmd("fetch")
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["result"], "3 result(s) listed, 3 fetched, 0 removed")
        self.assertEqual(r["events"], [{"type": "anam_concept2.fetched", "payload": {"fetched": [1001, 1002, 1000], "removed": []}}])
        self.assertEqual(sorted(p.name for p in self.cache.iterdir()), ["1000.json", "1001.json", "1002.json"])
        self.assertEqual(json.loads((self.cache / "1001.json").read_text()), {"result": ROW, "strokes": ROW_STROKES})
        self.assertEqual(json.loads((self.cache / "1002.json").read_text()), {"result": INTERVALS, "strokes": []})
        # The strokes were asked for once, for the one result that has them.
        self.assertEqual([p for p in self.logbook.requests if p.endswith("/strokes")], ["/api/users/me/results/1001/strokes"])
        again = self.run_cmd("fetch")
        self.assertEqual(again["result"], "3 result(s) listed, 0 fetched, 0 removed")
        self.assertEqual(again["events"], [])

    def test_fetch_reads_every_page_and_follows_the_listing_when_a_result_changes_or_goes(self):
        self.logbook.per_page = 2
        self.assertEqual(self.run_cmd("fetch")["result"], "3 result(s) listed, 3 fetched, 0 removed")
        self.assertEqual(len([p for p in self.logbook.requests if "/results?" in p]), 2)
        self.logbook.results = [dict(ROW, comments="felt good"), WEB]
        r = self.run_cmd("fetch")
        self.assertEqual(r["result"], "2 result(s) listed, 1 fetched, 1 removed")
        self.assertEqual(r["events"][0]["payload"], {"fetched": [1001], "removed": [1002]})
        self.assertFalse((self.cache / "1002.json").exists())
        self.assertEqual(json.loads((self.cache / "1001.json").read_text())["result"]["comments"], "felt good")

    def test_a_refused_token_is_not_retried_and_a_logbook_outage_is(self):
        r = self.run_cmd("fetch", token="wrong")
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])
        self.assertIn("401", r["error"])
        self.assertEqual(self.run_cmd("fetch", token=None)["retry"], False)
        self.logbook.status = 503
        r = self.run_cmd("fetch")
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(r["retry"])
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_a_redirect_is_refused_so_the_token_stays_home(self):
        self.logbook.redirect_to = "http://127.0.0.1:9/api/users/me/results"
        r = self.run_cmd("fetch")
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])
        self.assertIn("redirect", r["error"])
        self.assertEqual(len(self.logbook.requests), 1)

    def test_a_synced_workout_is_the_ieee_body_at_its_start_with_the_logbook_s_measures_beside_it(self):
        self.run_cmd("fetch")
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "ok", r)
        by_id = {p["id"]: p for p in payloads(r)}
        self.assertEqual(list(by_id), ["concept2:session:1000", "concept2:session:1001", "concept2:session:1002"])
        self.assertEqual(by_id["concept2:session:1001"], {
            "id": "concept2:session:1001", "activity_name": "rowing.machine",
            "effective_time_frame": {"time_interval": {"start_date_time": "2026-10-04T04:13:00Z",
                                                       "duration": {"value": 480, "unit": "sec"}}},
            "duration": {"value": 480, "unit": "sec"}, "source": "Concept2 Logbook", "start_time_known": True,
            "distance": {"value": 2000, "unit": "m"}, "kcal_burned": {"value": 120, "unit": "kcal"},
            "base_movement_quantity": {"value": 180, "unit": "strokes"}, "average_cadence": {"value": 22, "unit": "strokes/min"},
            "drag_factor": 110, "watt_minutes": 1200, "avg_hr_bpm": 150, "ending_hr_bpm": 155,
            "erg_type": "rower", "workout_type": "JustRow", "logbook_source": "ErgData Android",
            "logbook_date": "2026-10-04 15:21:00", "logbook_timezone": "Australia/Sydney", "weight_class": "H",
            "verified": True, "ranked": False,
            "splits": [
                {"position": 1, "duration_sec": 240, "distance_m": 1000, "kcal": 60, "watt_minutes": 600, "avg_spm": 22,
                 "avg_hr_bpm": 140, "max_hr_bpm": 150, "ending_hr_bpm": 150, "min_hr_bpm": 100},
                {"position": 2, "duration_sec": 240, "distance_m": 1000, "kcal": 60, "watt_minutes": 600, "avg_spm": 22,
                 "avg_hr_bpm": 158, "max_hr_bpm": 165, "ending_hr_bpm": 155, "min_hr_bpm": 150}],
            "stroke_series": [{"time_sec": 2.5, "distance_m": 6, "pace_500m_sec": 210, "spm": 20},
                              {"time_sec": 5.1, "distance_m": 12.5, "pace_500m_sec": 195, "spm": 23, "hr_bpm": 102}],
        })
        self.assertEqual(by_id["concept2:session:1002"]["splits"], [
            {"position": 1, "duration_sec": 140, "distance_m": 500, "kcal": 30, "avg_spm": 24, "rest_time_sec": 120,
             "avg_hr_bpm": 145, "max_hr_bpm": 162, "ending_hr_bpm": 160, "min_hr_bpm": 105, "rest_hr_bpm": 140}])
        self.assertEqual(by_id["concept2:session:1002"]["rest_time_sec"], 120)
        self.assertEqual(by_id["concept2:session:1002"]["rest_distance_m"], 200)
        self.assertEqual(by_id["concept2:session:1002"]["comments"], "one piece")
        self.assertNotIn("stroke_series", by_id["concept2:session:1002"])
        self.assertEqual(r["events"][0]["payload"]["snapshot"]["types"], ["activity.exercise-session"])
        self.assertNotIn("4800", json.dumps(by_id["concept2:session:1001"]))

    def test_a_workout_entered_on_the_web_starts_at_sydney_midnight_and_says_so(self):
        self.run_cmd("fetch")
        web = {p["id"]: p for p in payloads(self.run_cmd("poll"))}["concept2:session:1000"]
        self.assertEqual(web, {
            "id": "concept2:session:1000", "activity_name": "rowing.machine",
            "effective_time_frame": {"time_interval": {"start_date_time": "2021-01-15T00:00:00+11:00",
                                                       "duration": {"value": 1300, "unit": "sec"}}},
            "duration": {"value": 1300, "unit": "sec"}, "source": "Concept2 Logbook", "start_time_known": False,
            "distance": {"value": 5000, "unit": "m"}, "erg_type": "rower", "workout_type": "unknown",
            "logbook_source": "Web", "logbook_date": "2021-01-15 00:00:00", "weight_class": "H",
            "verified": False, "ranked": False})

    def test_handle_reads_only_recently_cached_results_and_is_no_snapshot(self):
        self.run_cmd("fetch")
        week_ago = time.time() - 7 * 86400
        os.utime(self.cache / "1000.json", (week_ago, week_ago))
        r = self.run_cmd("handle")
        self.assertEqual([p["id"] for p in payloads(r)], ["concept2:session:1001", "concept2:session:1002"])
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertEqual(self.run_cmd("handle", lookback_days=14)["result"], "3 workout(s) from 3 cached result(s), 1 batch(es)")

    def test_a_cached_file_that_will_not_read_is_logged_the_run_is_no_snapshot_and_health_fails(self):
        self.run_cmd("fetch")
        (self.cache / "1003.json").write_text("not json")
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(len(payloads(r)), 3)
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertTrue(any("1003.json" in line["message"] for line in r["logs"]), r["logs"])
        self.assertEqual(self.run_cmd("health")["status"], "error")
        (self.cache / "1003.json").unlink()
        h = self.run_cmd("health")
        self.assertEqual(h["status"], "ok", h)
        self.assertEqual(h["result"], "3 activity.exercise-session v1 from 3 cached result(s), every one conforming")

    def test_a_missing_cache_dir_is_not_retried(self):
        r = self.run_cmd("poll", cache_dir=str(self.cache / "nowhere"))
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])

    def test_the_definition_is_anam_s_and_the_garmin_importer_carries_the_same_one(self):
        ours = (REPO / "concept2" / "definitions" / "activity.exercise-session.json").read_bytes()
        self.assertEqual(ours, (REPO / "garmin" / "definitions" / "activity.exercise-session.json").read_bytes())

    @unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
    def test_every_workout_is_admitted_and_a_resend_is_no_op(self):
        self.run_cmd("fetch")
        daemon = Daemon("concept2", ["activity.exercise-session"])
        try:
            shaped = self.run_cmd("poll")
            for want in ("admitted", "no-op"):
                for ev in shaped["events"]:
                    r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                            "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                            "secrets": {"anam_importer_token_test": daemon.token}})
                    self.assertEqual(r["status"], "ok", r)
                    self.assertEqual(r["events"][0]["payload"]["outcomes"], {want: 3})
        finally:
            daemon.close()


if __name__ == "__main__":
    unittest.main()
