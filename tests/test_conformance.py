"""Payloads whose Definition names a pinned IEEE 1752 schema as its source_schema
pass that schema. The Definition is closed and the standard is not, so this is
what keeps the importer's shapes inside the standard."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft7Validator
from referencing import Registry, Resource

from tests.helpers import REPO
from tests.test_garmin import NIGHT, NO_SLEEP, garmin_db

PINNED = Path(__file__).resolve().parent / "conformance" / "ieee-1752"
BASE = "https://w3id.org/ieee/ieee-1752-schema/"


def pinned(name: str) -> Draft7Validator:
    registry = Registry()
    for f in PINNED.glob("*.json"):
        registry = registry.with_resource(BASE + f.name, Resource.from_contents(json.loads(f.read_text())))
    schema = json.loads((PINNED / f"{name}.json").read_text())
    schema["$id"] = BASE + f"{name}.json"  # resolve its relative $refs against the pinned files
    return Draft7Validator(schema, registry=registry, format_checker=Draft7Validator.FORMAT_CHECKER)


def module(path: Path):
    spec = importlib.util.spec_from_file_location(path.parent.name + "_run", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SleepEpisodeTest(unittest.TestCase):
    def test_garmin_nights_pass_the_pinned_sleep_episode_schema(self):
        definition = json.loads((REPO / "garmin" / "definitions" / "sleep.episode.json").read_text())
        self.assertEqual(definition["meta"]["source_schema"], "ieee-1752/sleep-episode-1.0")
        garmin = module(REPO / "garmin" / "run.py")
        spo2 = NIGHT[:8] + (94.0,) + NIGHT[9:11] + (88, "GOOD")
        with tempfile.TemporaryDirectory() as d:
            db = garmin_db(Path(d) / "garmin.db", [NIGHT, NO_SLEEP, ("2026-10-09",) + spo2[1:]])
            nights = garmin.sleeps({"garmin_db": str(db)})
        self.assertEqual(len(nights), 2)
        validator = pinned("sleep-episode-1.0")
        for night in nights:
            errors = [e.message for e in validator.iter_errors(night)]
            self.assertEqual(errors, [], night)

    def test_the_pinned_schema_is_not_a_pass_for_anything(self):
        bad = {"effective_time_frame": {"time_interval": {"start_date_time": "2026-10-07T12:44:00Z",
                                                          "end_date_time": "2026-10-07T18:42:00Z"}},
               "total_sleep_time": {"value": 349, "unit": "furlongs"}}
        self.assertTrue(list(pinned("sleep-episode-1.0").iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
