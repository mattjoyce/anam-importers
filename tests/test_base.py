import json
import tempfile
import unittest
from pathlib import Path

from anam_importer import Invalid, batches, check, envelope, load
from tests.helpers import REPO


class DefinitionsTest(unittest.TestCase):
    def setUp(self):
        self.defs = load(REPO / "withings")
        self.measurement = self.defs["health.measurement.withings"]

    def test_a_conforming_payload_has_no_errors(self):
        payload = {"withings_id": "1", "date": "2026-10-09 07:30:00", "type": "1", "value": "80.5", "unit": "-3",
                   "source_time": {"value": "2026-10-09 07:30:00", "zone": "UTC", "basis": "source"}}
        self.assertEqual(self.measurement.errors(payload), [])

    def test_every_failure_is_named(self):
        errors = self.measurement.errors({"withings_id": "1", "date": "x", "type": "1", "value": "eighty",
                                          "unit": "-3", "colour": "red",
                                          "source_time": {"value": "x", "zone": "UTC", "basis": "source"}})
        self.assertEqual(len(errors), 2, errors)
        self.assertTrue(any("value" in e for e in errors))
        self.assertTrue(any("colour" in e for e in errors))

    def test_check_refuses_with_every_problem(self):
        good = envelope(self.measurement, {"withings_id": "1", "date": "d", "type": "1", "value": "1", "unit": "-3"})
        bad = envelope(self.measurement, {"withings_id": "1"})
        other = {"type": "health.sleep", "definition_version": 1, "payload": {}}
        with self.assertRaises(Invalid) as caught:
            check(self.defs, [good, bad, other])
        self.assertEqual(len([p for p in caught.exception.problems if p.startswith("envelope 1")]), 5)
        self.assertTrue(any(p.startswith("envelope 2") for p in caught.exception.problems))

    def test_an_envelope_names_no_source(self):
        env = envelope(self.measurement, {"x": 1}, asserted_person="person-a")
        self.assertEqual(set(env), {"type", "definition_version", "payload", "asserted_person"})
        self.assertEqual(env["definition_version"], self.measurement.version)


def manifest(typ: str, version: int) -> str:
    return json.dumps({"meta": {"facet_type": typ, "definition_version": version, "classification": "Normal",
                                "validation_mode": "strict", "source_schema": "test/x",
                                "time_semantics": {"fact_time": {"pointer": "/at", "layout": "2006-01-02T15:04:05Z07:00",
                                                                 "zone": "UTC"}},
                                "identity_key": ["/id"]},
                       "schema": {"type": "object", "properties": {"id": {"type": "string"}}}})


class HistoryTest(unittest.TestCase):
    """An importer registers every version of the types it emits now, oldest first
    (anam card 198); a history file under an old name is Anam's, not registered."""

    def folder(self, current, history):
        d = Path(self.tmp.name)
        (d / "definitions" / "history").mkdir(parents=True)
        for name, (typ, v) in current.items():
            (d / "definitions" / name).write_text(manifest(typ, v))
        for name, (typ, v) in history.items():
            (d / "definitions" / "history" / name).write_text(manifest(typ, v))
        return d

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_every_version_of_a_type_it_emits_now_is_registered_oldest_first(self):
        d = self.folder({"a.x.json": ("a.x", 3), "b.y.json": ("b.y", 1)},
                        {"a.x.v2.json": ("a.x", 2), "a.x.v1.json": ("a.x", 1), "a.old.v4.json": ("a.old", 4)})
        defs = load(d)
        self.assertEqual({t: x.version for t, x in defs.items()}, {"a.x": 3, "b.y": 1})
        self.assertEqual([(x.type, x.version) for x in defs.every], [("a.x", 1), ("a.x", 2), ("a.x", 3), ("b.y", 1)])
        self.assertEqual([json.loads(m)["meta"]["definition_version"] for m in defs.manifests(["a.x"])], [1, 2, 3])
        self.assertEqual(len(defs.manifests()), 4)

    def test_a_history_file_must_be_named_for_its_version_and_be_older(self):
        cases = {
            "misnamed": ({"a.x.v1.json": ("a.x", 2)}, "name the file a.x.v2.json"),
            "not older": ({"a.x.v3.json": ("a.x", 3)}, "not older"),
        }
        for name, (history, says) in cases.items():
            with self.subTest(name):
                self.tmp.cleanup()
                self.tmp = tempfile.TemporaryDirectory()
                d = self.folder({"a.x.json": ("a.x", 3)}, history)
                with self.assertRaises(ValueError) as caught:
                    load(d)
                self.assertIn(says, str(caught.exception))

    def test_the_importers_carry_their_history_and_no_old_name_is_sent(self):
        withings = load(REPO / "withings")
        self.assertEqual([(x.type, x.version) for x in withings.every],
                         [("health.measurement.withings", 1), ("health.measurement.withings", 2)])
        garmin = load(REPO / "garmin")
        self.assertNotIn("activity.day", {x.type for x in garmin.every})  # the vendor leaf's old name


class ProtocolTest(unittest.TestCase):
    def test_an_unexpected_exception_is_still_a_protocol_response(self):
        import io
        import json
        import sys
        from unittest import mock

        from anam_importer import ductile

        def broken(_request):
            raise RuntimeError("boom")

        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO('{"command": "poll"}')), mock.patch.object(sys, "stdout", out):
            ductile.run({"poll": broken})
        response = json.loads(out.getvalue())
        self.assertEqual(response["status"], "error")
        self.assertFalse(response["retry"])
        self.assertIn("boom", response["error"])

    def test_a_failure_carries_its_retry(self):
        import io
        import json
        import sys
        from unittest import mock

        from anam_importer import ductile

        def busy(_request):
            raise ductile.Failure("source is busy", retry=True)

        out = io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO('{"command": "poll"}')), mock.patch.object(sys, "stdout", out):
            ductile.run({"poll": busy})
        self.assertTrue(json.loads(out.getvalue())["retry"])


class BatchesTest(unittest.TestCase):
    def test_batches_hold_at_most_49(self):
        sizes = [len(b) for b in batches(list(range(100)))]
        self.assertEqual(sizes, [49, 49, 2])

    def test_a_batch_size_past_the_gate_is_refused(self):
        with self.assertRaises(ValueError):
            list(batches([1], size=50))


if __name__ == "__main__":
    unittest.main()
