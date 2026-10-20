"""anam_owntracks over a spool shaped as the owntracks plugin writes it. Coordinates are
made up."""

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

ENTRY = REPO / "owntracks" / "run.py"

# HOUR is 2026-01-01T00:00:00Z; NOW is a receipt time well inside any lookback.
HOUR = 1767225600


def body(tst, lat=10.5, lon=20.25, **extra):
    """An OwnTracks location body, as the Android app posts it."""
    b = {"_type": "location", "_id": f"m{tst}", "topic": "owntracks/user/phone-a", "qos": 1, "retained": False,
         "created_at": tst + 1, "source": "fused", "batt": 81, "bs": 1, "acc": 14, "lat": lat, "lon": lon, "alt": 42,
         "cog": 0, "tst": tst, "m": 1, "conn": "w", "inregions": [], "BSSID": "00:11:22:33:44:55", "SSID": "net-a",
         "tid": "pa", "t": "p", "vel": 0}
    b.update(extra)
    return b


class Spool:
    """A spool directory with lines appended the way the pull appends them."""

    def __init__(self, root: Path):
        self.root = root
        self.next_id = 1

    def add(self, b, device="phone-a", received=None, raw=None):
        received = received if received is not None else int(time.time())
        path = self.root / device / time.strftime("%Y-%m.jsonl", time.gmtime(received))
        path.parent.mkdir(parents=True, exist_ok=True)
        text = raw if raw is not None else (json.dumps(b) if isinstance(b, dict) else b)
        tst = b.get("tst") if isinstance(b, dict) else None
        kind = b.get("_type") if isinstance(b, dict) else None
        line = {"id": self.next_id, "user": "user", "device": device, "type": kind, "tst": tst,
                "received_at": received, "body": text}
        self.next_id += 1
        with path.open("a") as fh:
            fh.write(json.dumps(line) + "\n")
        return path


class OwnTracksTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.spool = Spool(Path(self.tmp.name) / "spool")
        self.spool.root.mkdir()
        self.config = {"spool_dir": str(self.spool.root), "person_id": "person-a"}

    def tearDown(self):
        self.tmp.cleanup()

    def run_cmd(self, command):
        return run_plugin(ENTRY, {"command": command, "config": self.config})

    def envelopes(self, r):
        self.assertEqual(r["status"], "ok", r)
        return [e for ev in r["events"] for e in ev["payload"]["envelopes"]]

    def test_points_are_grouped_by_phone_and_utc_hour(self):
        self.spool.add(body(HOUR + 60))
        self.spool.add(body(HOUR + 3599, lat=10.6))
        self.spool.add(body(HOUR + 3600, lat=10.7))
        self.spool.add(body(HOUR + 120), device="phone-b")
        envs = self.envelopes(self.run_cmd("poll"))
        self.assertEqual([e["payload"]["id"] for e in envs], [
            "loc:phone-a:2026-01-01T00:00:00Z", "loc:phone-b:2026-01-01T00:00:00Z", "loc:phone-a:2026-01-01T01:00:00Z"])
        first = envs[0]["payload"]
        self.assertEqual(first["hour"], "2026-01-01T00:00:00Z")
        self.assertEqual(first["device"], "phone-a")
        self.assertEqual([p["t"] for p in first["points"]], ["2026-01-01T00:01:00Z", "2026-01-01T00:59:59Z"])
        self.assertEqual(envs[0]["type"], "place.track")
        self.assertEqual(envs[0]["asserted_person"], "person-a")

    def test_a_point_keeps_what_the_phone_wrote(self):
        self.spool.add(body(HOUR + 60, vac=3, inregions=["home"], vel=5))
        p = self.envelopes(self.run_cmd("poll"))[0]["payload"]["points"][0]
        self.assertEqual(p, {"t": "2026-01-01T00:01:00Z", "lat": 10.5, "lon": 20.25, "acc": 14, "alt": 42, "vac": 3,
                             "vel": 5, "cog": 0, "batt": 81, "bs": 1, "conn": "w", "ssid": "net-a",
                             "bssid": "00:11:22:33:44:55", "inregions": ["home"], "monitoring": 1,
                             "location_source": "fused", "triggers": ["p"], "tid": "pa"})

    def test_messages_for_one_fix_are_one_point_with_every_trigger(self):
        self.spool.add(body(HOUR + 60, t="u"))
        self.spool.add(body(HOUR + 60, t="p", _id="other", created_at=HOUR + 99))
        self.spool.add(body(HOUR + 60, t="p"))
        points = self.envelopes(self.run_cmd("poll"))[0]["payload"]["points"]
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["triggers"], ["u", "p"])

    def test_a_different_fix_at_the_same_time_is_dropped_and_counted(self):
        self.spool.add(body(HOUR + 60))
        self.spool.add(body(HOUR + 60, lat=11.0))
        r = self.run_cmd("poll")
        points = self.envelopes(r)[0]["payload"]["points"]
        self.assertEqual(points[0]["lat"], 10.5, "the first received wins")
        self.assertIn("messages dropped for sharing a fix time with a different fix: phone-a 1",
                      [line["message"] for line in r["logs"]])
        self.assertIn("snapshot", r["events"][0]["payload"], "a duplicate is the source as it is, not a gap")

    def test_other_messages_and_empty_bodies_are_skipped(self):
        self.spool.add({"_type": "status", "_id": "s", "topic": "t", "android": {}})
        self.spool.add({"_type": "transition", "event": "enter", "tst": HOUR})
        self.spool.add(None, raw="")
        self.spool.add(body(HOUR + 60))
        r = self.run_cmd("poll")
        self.assertEqual(len(self.envelopes(r)), 1)
        self.assertIn("skipped messages that are not locations: empty 1, status 1, transition 1",
                      [line["message"] for line in r["logs"]])
        self.assertIn("snapshot", r["events"][0]["payload"])

    def test_unknown_fields_are_counted_and_left_out(self):
        self.spool.add(body(HOUR + 60, poi="cafe", p=101.2))
        r = self.run_cmd("poll")
        p = self.envelopes(r)[0]["payload"]["points"][0]
        self.assertNotIn("poi", p)
        self.assertIn("body fields the Definition does not keep: p 1, poi 1", [line["message"] for line in r["logs"]])

    def test_unknown_values_are_left_out(self):
        self.spool.add(body(HOUR + 60, acc=-1, vel=-1, batt=-1, bs=9, conn=""))
        p = self.envelopes(self.run_cmd("poll"))[0]["payload"]["points"][0]
        for key in ("acc", "vel", "batt", "bs", "conn"):
            self.assertNotIn(key, p)

    def test_a_bad_line_is_logged_without_its_content_and_breaks_the_snapshot(self):
        path = self.spool.add(body(HOUR + 60))
        with path.open("a") as fh:
            fh.write("{not json\n")
        self.spool.add(None, raw="{\"_type\":\"location\",\"lat\":")
        self.spool.add(body(HOUR + 120, lat=200))
        r = self.run_cmd("poll")
        self.assertEqual(len(self.envelopes(r)), 1)
        logs = " ".join(line["message"] for line in r["logs"])
        self.assertIn("line 2: JSONDecodeError", logs)
        self.assertIn("the body is not JSON", logs)
        self.assertIn("no coordinates", logs)
        self.assertNotIn("200", logs)
        self.assertNotIn("snapshot", r["events"][0]["payload"])

    def test_a_last_line_still_being_written_is_not_read(self):
        path = self.spool.add(body(HOUR + 60))
        with path.open("a") as fh:
            fh.write('{"id": 99, "body": "{\\"_type\\":\\"loc')
        r = self.run_cmd("poll")
        self.assertEqual(r["logs"], [])
        self.assertIn("snapshot", r["events"][0]["payload"])

    def test_handle_sends_whole_hours_that_gained_a_message(self):
        old = int(time.time()) - 10 * 86400
        self.spool.add(body(HOUR + 60), received=old)
        self.spool.add(body(HOUR + 7200), received=old)
        self.spool.add(body(HOUR + 120))  # a late flush into the first hour, received now
        envs = self.envelopes(self.run_cmd("handle"))
        self.assertEqual(len(envs), 1)
        self.assertEqual(envs[0]["payload"]["hour"], "2026-01-01T00:00:00Z")
        self.assertEqual(len(envs[0]["payload"]["points"]), 2, "the hour goes whole, old point included")
        self.assertNotIn("snapshot", self.run_cmd("handle")["events"][0]["payload"])

    def test_poll_batches_and_labels_one_snapshot(self):
        for h in range(60):
            self.spool.add(body(HOUR + h * 3600 + 5))
        r = self.run_cmd("poll")
        self.assertEqual(len(r["events"]), 2)
        parts = [ev["payload"]["snapshot"] for ev in r["events"]]
        self.assertEqual([(p["part"], p["parts"]) for p in parts], [(1, 2), (2, 2)])
        self.assertEqual(parts[0]["types"], ["place.track"])
        self.assertEqual(len({p["id"] for p in parts}), 1)

    def test_an_hour_over_max_payload_bytes_is_skipped_and_breaks_the_snapshot(self):
        self.spool.add(body(HOUR + 60))
        self.spool.add(body(HOUR + 3600 + 60))
        self.config["max_payload_bytes"] = 100
        r = self.run_cmd("poll")
        self.assertEqual(self.envelopes(r), [])
        self.assertEqual(sum("over 100" in line["message"] for line in r["logs"]), 2, r["logs"])

    def test_an_empty_spool_sends_nothing(self):
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"], [])

    def test_no_coordinates_in_logs_or_results(self):
        self.spool.add(body(HOUR + 60, lat=-33.123456, lon=151.654321, poi="x"))
        self.spool.add(body(HOUR + 60, lat=-34.123456, lon=152.654321))
        for command in ("poll", "handle", "health"):
            r = self.run_cmd(command)
            text = json.dumps({k: v for k, v in r.items() if k != "events"})
            for coord in ("33.12", "151.65", "34.12", "152.65"):
                self.assertNotIn(coord, text, command)

    def test_health(self):
        self.spool.add(body(HOUR + 60))
        r = self.run_cmd("health")
        self.assertEqual(r["status"], "ok", r)
        self.assertIn("1 place.track v1 hour(s) from 1 spool line(s), every one conforming", r["result"])
        self.spool.add(body(HOUR + 120, lat="x"))
        self.assertEqual(self.run_cmd("health")["status"], "error")

    def test_a_missing_spool_is_not_retried(self):
        self.config["spool_dir"] = str(Path(self.tmp.name) / "nowhere")
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["retry"])


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN is not set")
class OwnTracksAgainstAnamTest(unittest.TestCase):
    def setUp(self):
        self.daemon = Daemon("owntracks", ["place.track"])
        self.tmp = tempfile.TemporaryDirectory()
        self.spool = Spool(Path(self.tmp.name) / "spool")
        self.spool.root.mkdir()
        self.config = {"spool_dir": str(self.spool.root), "person_id": "person-a"}

    def tearDown(self):
        self.daemon.close()
        self.tmp.cleanup()

    def resend(self, command="poll"):
        shaped = run_plugin(ENTRY, {"command": command, "config": self.config})
        self.assertEqual(shaped["status"], "ok", shaped)
        submit = REPO / "anam_submit" / "run.py"
        out = []
        for ev in shaped["events"]:
            r = run_plugin(submit, {"command": "handle",
                                    "config": {"anam_url": self.daemon.url, "token_secret": "anam_importer_token_test"},
                                    "secrets": {"anam_importer_token_test": self.daemon.token}, "event": ev})
            self.assertEqual(r["status"], "ok", r)
            out.append(r)
        return out

    def outcomes(self, results):
        total = {}
        for r in results:
            for k, n in r["events"][0]["payload"]["outcomes"].items():
                total[k] = total.get(k, 0) + n
        return total

    def test_hours_are_admitted_resends_are_no_ops_and_a_late_point_supersedes_its_hour(self):
        self.spool.add(body(HOUR + 60))
        self.spool.add(body(HOUR + 60, t="u"))
        self.spool.add(body(HOUR + 3700))
        self.assertEqual(self.outcomes(self.resend()), {"admitted": 2})
        self.assertEqual(self.outcomes(self.resend()), {"no-op": 2})
        self.spool.add(body(HOUR + 1800, lat=10.9))
        self.assertEqual(self.outcomes(self.resend("handle")), {"superseded": 1, "no-op": 1})


if __name__ == "__main__":
    unittest.main()
