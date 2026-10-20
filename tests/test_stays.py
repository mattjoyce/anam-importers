"""anam_stays over a spool shaped as the owntracks plugin writes it. Coordinates are
real Dubai points so the stay geometry is honest; no test reaches the network."""

import json
import tempfile
import time
import unittest
from pathlib import Path

from stays.geocode import Cache, geocoder, name_from, place_from
from stays.run import Fix, detect_stays, handle, health, poll
from tests.helpers import REPO, run_plugin

ENTRY = REPO / "stays" / "run.py"

# BASE is 2026-10-17T02:00:00Z. SPOT_A is near Dubai airport; SPOT_B is a few km off.
BASE = 1792202400
SPOT_A = (25.2422, 55.3744)
SPOT_B = (25.2700, 55.3300)


def spool_line(buffer_id, device, tst, lat, lon, received=None):
    body = json.dumps({"_type": "location", "tst": tst, "lat": lat, "lon": lon, "acc": 12})
    return json.dumps({"id": buffer_id, "body": body, "received_at": received if received is not None else tst})


def write_spool(root, device, lines):
    d = root / device
    d.mkdir(parents=True, exist_ok=True)
    (d / "2026-10.jsonl").write_text("\n".join(lines) + "\n")


def osm(name_city="Dubai"):
    """A Nominatim-shaped answer for SPOT_A."""
    return {"data": {"display_name": f"Dubai International Airport, {name_city}, United Arab Emirates",
                     "osm_type": "way", "osm_id": 12345678,
                     "address": {"aeroway": "Dubai International Airport", "city": name_city,
                                 "country": "United Arab Emirates", "country_code": "ae"}},
            "at": "2026-10-17T03:00:00Z"}


def fixes_at(device, spot, start, count, step=180, jitter=0.0):
    """count fixes step seconds apart at spot, each nudged jitter degrees east."""
    return [Fix(device, start + i * step, spot[0], spot[1] + i * jitter, start + i * step) for i in range(count)]


class DetectStays(unittest.TestCase):
    def test_a_dwell_becomes_one_stay(self):
        # Six fixes over 15 minutes within a few metres: one stay.
        stays = detect_stays(fixes_at("tokay", SPOT_A, BASE, 6, step=180, jitter=0.00001), 100.0, 600)
        self.assertEqual(len(stays), 1)
        self.assertEqual(stays[0].start, "2026-10-17T02:00:00Z")
        self.assertEqual(stays[0].end, "2026-10-17T02:15:00Z")
        self.assertEqual(len(stays[0].fixes), 6)
        self.assertLess(stays[0].radius_m(), 10)

    def test_a_brief_pass_is_not_a_stay(self):
        # Two fixes three minutes apart: under the ten-minute dwell, so no stay.
        stays = detect_stays(fixes_at("tokay", SPOT_A, BASE, 2, step=180), 100.0, 600)
        self.assertEqual(stays, [])

    def test_two_places_split(self):
        fixes = fixes_at("tokay", SPOT_A, BASE, 6, step=180)
        fixes += fixes_at("tokay", SPOT_B, BASE + 3600, 6, step=180)
        stays = detect_stays(fixes, 100.0, 600)
        self.assertEqual(len(stays), 2)
        self.assertGreater(stays[1].fixes[0].tst, stays[0].fixes[-1].tst)

    def test_payload_carries_place_when_named(self):
        stay = detect_stays(fixes_at("tokay", SPOT_A, BASE, 6, step=180), 100.0, 600)[0]
        p = stay.payload(lambda lat, lon: osm())
        self.assertEqual(p["id"], "stay:tokay:2026-10-17T02:00:00Z")
        self.assertEqual(p["device"], "tokay")
        self.assertEqual(p["fixes"], 6)
        self.assertEqual(p["place"]["name"], "Dubai, United Arab Emirates")
        self.assertEqual(p["place"]["osm_id"], 12345678)
        self.assertEqual(p["place"]["geocoded_at"], "2026-10-17T03:00:00Z")

    def test_payload_placeless_when_not_named(self):
        stay = detect_stays(fixes_at("tokay", SPOT_A, BASE, 6, step=180), 100.0, 600)[0]
        p = stay.payload(lambda lat, lon: None)
        self.assertNotIn("place", p)


class Naming(unittest.TestCase):
    def test_ladder_prefers_the_specific(self):
        # city and state are both "Dubai"; a repeated part is said once.
        data = {"address": {"suburb": "Al Garhoud", "city": "Dubai", "state": "Dubai",
                            "country": "United Arab Emirates"}, "display_name": "x"}
        self.assertEqual(name_from(data), "Al Garhoud, Dubai, United Arab Emirates")

    def test_ladder_falls_back_to_display_name(self):
        self.assertEqual(name_from({"address": {}, "display_name": "Somewhere"}), "Somewhere")

    def test_place_from_none_without_a_name(self):
        self.assertIsNone(place_from({"address": {}}, "2026-10-17T03:00:00Z"))


class CacheNamesACellOnce(unittest.TestCase):
    def test_second_lookup_hits_the_cache(self):
        calls = {"n": 0}

        class Stub:
            def reverse(self, lat, lon):
                calls["n"] += 1
                return {"display_name": "D", "address": {"city": "Dubai"}}

        with tempfile.TemporaryDirectory() as tmp:
            look = geocoder(Stub(), Cache(Path(tmp)))
            first = look(25.2422, 55.3744)
            second = look(25.2422, 55.3744)
            self.assertEqual(calls["n"], 1)
            self.assertEqual(first["data"], second["data"])


class DefinitionIsStrict(unittest.TestCase):
    """Anam's strict mode refuses any object subschema that does not set additionalProperties
    (false, or a value schema). The live daemon enforces this when it registers the Definition
    on the first batch, so a miss means a deploy that wires up and then 422s. This catches it
    here, without the daemon. (place.stay v1's place.address regressed exactly this way.)"""

    def _objects_missing_additional_properties(self, node, path="schema"):
        bad = []
        if not isinstance(node, dict):
            return bad
        t = node.get("type")
        is_object = t == "object" or (isinstance(t, list) and "object" in t)
        if is_object and "additionalProperties" not in node:
            bad.append(path)
        for key in ("properties", "$defs", "definitions"):
            for name, sub in (node.get(key) or {}).items():
                bad += self._objects_missing_additional_properties(sub, f"{path}/{key}/{name}")
        for key in ("items", "additionalProperties", "contains"):
            if isinstance(node.get(key), dict):
                bad += self._objects_missing_additional_properties(node[key], f"{path}/{key}")
        return bad

    def test_every_object_sets_additional_properties(self):
        schema = json.loads((REPO / "stays" / "definitions" / "place.stay.json").read_text())["schema"]
        self.assertEqual(self._objects_missing_additional_properties(schema), [])


class Plugin(unittest.TestCase):
    """The whole plugin over a real spool, the geocoder pointed at a closed port so no
    call can be made: stays still emit, placeless, as when OSM is down."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.spool = root / "spool"
        self.cache = root / "cache"
        lines = [spool_line(i + 1, "tokay", BASE + i * 180, SPOT_A[0], SPOT_A[1] + i * 0.00001)
                 for i in range(6)]
        write_spool(self.spool, "tokay", lines)
        self.config = {"spool_dir": str(self.spool), "person_id": "person-a", "geocache_dir": str(self.cache),
                       "rate_limit_seconds": 0, "geocode_endpoint": "http://127.0.0.1:1/reverse"}

    def tearDown(self):
        self.tmp.cleanup()

    def _envelopes(self, resp):
        out = []
        for ev in resp["events"]:
            out.extend(ev["payload"]["envelopes"])
        return out

    def test_handle_emits_a_conforming_placeless_stay(self):
        # The spool's fixes are at BASE, a fixed day, so the lookback reaches back to it
        # however long after that day the test runs.
        days = (time.time() - BASE) / 86400 + 1
        resp = run_plugin(ENTRY, {"command": "handle", "config": {**self.config, "lookback_days": days}})
        self.assertEqual(resp["status"], "ok", resp)
        envs = self._envelopes(resp)
        self.assertEqual(len(envs), 1)
        p = envs[0]["payload"]
        self.assertEqual(envs[0]["type"], "place.stay")
        self.assertEqual(p["id"], "stay:tokay:2026-10-17T02:00:00Z")
        self.assertEqual(p["fixes"], 6)
        self.assertNotIn("place", p)  # the geocoder could not be reached

    def test_poll_labels_a_snapshot(self):
        resp = run_plugin(ENTRY, {"command": "poll", "config": self.config})
        self.assertEqual(resp["status"], "ok", resp)
        snapshots = [ev["payload"].get("snapshot") for ev in resp["events"]]
        self.assertTrue(all(s and s["types"] == ["place.stay"] for s in snapshots))

    def test_health_passes_on_a_readable_spool(self):
        resp = run_plugin(ENTRY, {"command": "health", "config": self.config})
        self.assertEqual(resp["status"], "ok", resp)

    def test_handle_in_process_matches(self):
        # The same request without a subprocess, so a failure points at the code.
        resp = handle({"config": self.config})
        self.assertEqual(resp["status"], "ok", resp)
        self.assertEqual(poll({"config": self.config})["status"], "ok")
        self.assertEqual(health({"config": self.config})["status"], "ok")


if __name__ == "__main__":
    unittest.main()
