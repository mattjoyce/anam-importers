import unittest

from anam_importer import Invalid, batches, check, envelope, load
from tests.helpers import REPO


class DefinitionsTest(unittest.TestCase):
    def setUp(self):
        self.defs = load(REPO / "withings")
        self.measurement = self.defs["health.measurement"]

    def test_a_conforming_payload_has_no_errors(self):
        payload = {"withings_id": "1", "date": "2026-10-09 07:30:00", "type": "1", "value": "80.5", "unit": "-3"}
        self.assertEqual(self.measurement.errors(payload), [])

    def test_every_failure_is_named(self):
        errors = self.measurement.errors({"withings_id": "1", "date": "x", "type": "1", "value": "eighty",
                                          "unit": "-3", "colour": "red"})
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any("value" in e for e in errors))
        self.assertTrue(any("colour" in e for e in errors))

    def test_check_refuses_with_every_problem(self):
        good = envelope(self.measurement, {"withings_id": "1", "date": "d", "type": "1", "value": "1", "unit": "-3"})
        bad = envelope(self.measurement, {"withings_id": "1"})
        other = {"type": "health.sleep", "definition_version": 1, "payload": {}}
        with self.assertRaises(Invalid) as caught:
            check(self.defs, [good, bad, other])
        self.assertEqual(len([p for p in caught.exception.problems if p.startswith("envelope 1")]), 4)
        self.assertTrue(any(p.startswith("envelope 2") for p in caught.exception.problems))

    def test_an_envelope_names_no_source(self):
        env = envelope(self.measurement, {"x": 1}, asserted_person="matt")
        self.assertEqual(set(env), {"type", "definition_version", "payload", "asserted_person"})
        self.assertEqual(env["definition_version"], self.measurement.version)


class BatchesTest(unittest.TestCase):
    def test_batches_hold_at_most_49(self):
        sizes = [len(b) for b in batches(list(range(100)))]
        self.assertEqual(sizes, [49, 49, 2])

    def test_a_batch_size_past_the_gate_is_refused(self):
        with self.assertRaises(ValueError):
            list(batches([1], size=50))


if __name__ == "__main__":
    unittest.main()
