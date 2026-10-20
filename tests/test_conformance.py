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
from tests.test_garmin import DAY, EMPTY_DAY, NIGHT, NO_SLEEP, garmin_db, sleep_json, summary

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
        definition = json.loads((REPO / "garmin" / "definitions" / "health.sleep-episode.json").read_text())
        self.assertEqual(definition["meta"]["source_schema"], "ieee-1752/sleep-episode-1.0")
        garmin = module(REPO / "garmin" / "run.py")
        spo2 = NIGHT[:8] + (94.0,) + NIGHT[9:11] + (88, "GOOD")
        with tempfile.TemporaryDirectory() as d:
            db = garmin_db(Path(d) / "garmin.db", [NIGHT, NO_SLEEP, ("2015-10-09",) + spo2[1:]])
            for day in ("2015-10-08", "2015-10-09"):
                sleep_json(Path(d), day, "2015-10-07T12:44:00+11:00", "2015-10-07T18:42:00+11:00")
            nights, _ = garmin.sleeps({"garmin_db": str(db), "sleep_dir": d}, garmin.DEFAULT_BUSY_MS)
        self.assertEqual(len(nights), 2)
        validator = pinned("ieee-1752/sleep-episode-1.0")
        for night in nights:
            errors = [e.message for e in validator.iter_errors(night)]
            self.assertEqual(errors, [], night)

    def test_the_pinned_schema_is_not_a_pass_for_anything(self):
        bad = {"effective_time_frame": {"time_interval": {"start_date_time": "2015-10-07T12:44:00Z",
                                                          "end_date_time": "2015-10-07T18:42:00Z"}},
               "total_sleep_time": {"value": 349, "unit": "furlongs"}}
        self.assertTrue(list(pinned("ieee-1752/sleep-episode-1.0").iter_errors(bad)))


class HeartRateDailyTest(unittest.TestCase):
    def test_garmin_s_daily_figures_pass_the_pinned_heart_rate_schema(self):
        definition = json.loads((REPO / "garmin" / "definitions" / "health.heart-rate-day.json").read_text())
        validator = pinned(definition["meta"]["source_schema"])
        garmin = module(REPO / "garmin" / "run.py")
        with tempfile.TemporaryDirectory() as d:
            db = garmin_db(Path(d) / "garmin.db", [], resting=[("2015-10-09", 61.0)], daily=[("2015-10-09", 59, 135)])
            summary(Path(d), "2015-10-09", "2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00")
            figures = garmin.days({"garmin_db": str(db), "fit_dir": d}, garmin.DEFAULT_BUSY_MS).heart
        self.assertEqual([f["statistic"] for f in figures], ["resting", "minimum", "maximum"])
        for figure in figures:
            self.assertEqual([e.message for e in validator.iter_errors(figure)], [], figure)

    def test_the_pinned_schema_refuses_a_statistic_omh_does_not_name(self):
        bad = {"heart_rate": {"value": 61, "unit": "beats/min"}, "descriptive_statistic": "resting",
               "effective_time_frame": {"date_time": "2015-10-09T00:00:00+11:00"}}
        self.assertTrue(list(pinned("omh/heart-rate-2.0").iter_errors(bad)))


class StepCountTest(unittest.TestCase):
    def test_garmin_s_daily_steps_pass_the_pinned_step_count_schema(self):
        definition = json.loads((REPO / "garmin" / "definitions" / "activity.steps.json").read_text())
        validator = pinned(definition["meta"]["source_schema"])
        garmin = module(REPO / "garmin" / "run.py")
        with tempfile.TemporaryDirectory() as d:
            summary(Path(d), "2015-10-09", "2015-10-09T00:00:00+11:00", "2015-10-10T00:00:00+11:00", steps=6219)
            db = garmin_db(Path(d) / "garmin.db", [], daily=[DAY, EMPTY_DAY])
            steps = garmin.days({"garmin_db": str(db), "fit_dir": d}, garmin.DEFAULT_BUSY_MS).steps
        self.assertEqual(len(steps), 1)
        self.assertEqual([e.message for e in validator.iter_errors(steps[0])], [], steps[0])

    def test_the_pinned_schema_refuses_steps_counted_in_another_unit(self):
        bad = {"step_count": {"value": 6219, "unit": "paces"},
               "effective_time_frame": {"time_interval": {"start_date_time": "2015-10-09T00:00:00+11:00",
                                                          "end_date_time": "2015-10-10T00:00:00+11:00"}}}
        self.assertTrue(list(pinned("omh/step-count-3.0").iter_errors(bad)))


if __name__ == "__main__":
    unittest.main()
