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

CONFORMANCE = Path(__file__).resolve().parent / "conformance"
# Where each family's schemas say they live; their relative $refs resolve against it.
BASES = {"ieee-1752": "https://w3id.org/ieee/ieee-1752-schema/",
         "omh": "https://w3id.org/openmhealth/schemas/omh/"}


def pinned(source_schema: str) -> Draft7Validator:
    """The validator for a Definition's source_schema, "<family>/<name>", resolving
    only against the pinned files, so nothing is fetched."""
    family, name = source_schema.split("/")
    base, folder = BASES[family], CONFORMANCE / family
    registry = Registry()
    for f in folder.glob("*.json"):
        contents = json.loads(f.read_text())
        contents.pop("$id", None)  # each is registered under the name the $refs use
        registry = registry.with_resource(base + f.name, Resource.from_contents(contents))
    schema = json.loads((folder / f"{name}.json").read_text())
    schema["$id"] = base + f"{name}.json"
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
        validator = pinned("ieee-1752/sleep-episode-1.0")
        for night in nights:
            errors = [e.message for e in validator.iter_errors(night)]
            self.assertEqual(errors, [], night)

    def test_the_pinned_schema_is_not_a_pass_for_anything(self):
        bad = {"effective_time_frame": {"time_interval": {"start_date_time": "2026-10-07T12:44:00Z",
                                                          "end_date_time": "2026-10-07T18:42:00Z"}},
               "total_sleep_time": {"value": 349, "unit": "furlongs"}}
        self.assertTrue(list(pinned("ieee-1752/sleep-episode-1.0").iter_errors(bad)))


class HeartRateDailyTest(unittest.TestCase):
    def test_garmin_s_daily_figures_pass_the_pinned_heart_rate_schema(self):
        definition = json.loads((REPO / "garmin" / "definitions" / "health.heart-rate-daily.json").read_text())
        validator = pinned(definition["meta"]["source_schema"])
        garmin = module(REPO / "garmin" / "run.py")
        with tempfile.TemporaryDirectory() as d:
            db = garmin_db(Path(d) / "garmin.db", [], resting=[("2026-10-09", 61.0)], daily=[("2026-10-09", 59, 135)])
            figures = garmin.heart_rates({"garmin_db": str(db)})
        self.assertEqual([f["statistic"] for f in figures], ["resting", "minimum", "maximum"])
        for figure in figures:
            self.assertEqual([e.message for e in validator.iter_errors(figure)], [], figure)

    def test_the_pinned_schema_refuses_a_statistic_omh_does_not_name(self):
        bad = {"heart_rate": {"value": 61, "unit": "beats/min"}, "descriptive_statistic": "resting",
               "effective_time_frame": {"date_time": "2026-10-09T00:00:00+11:00"}}
        self.assertTrue(list(pinned("omh/heart-rate-2.0").iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
