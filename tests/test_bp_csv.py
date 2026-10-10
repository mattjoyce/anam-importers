"""anam_bp_csv: the export read as Anam's built-in bpcsv worker reads it."""

import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

BP = REPO / "bp_csv" / "run.py"
SUBMIT = REPO / "anam_submit" / "run.py"

# The fixture of the built-in worker's own tests (internal/capture/bpcsv): "\t "-padded
# fields, CRLF, quotes inside padded fields, a trailing empty column, unpadded month and
# day digits, two distinct readings sharing a timestamp, sparse cells, and a typo in a
# comment, which is the source's to keep.
HEADER = ("Date (Excel),\tDate,\tSystolic,\tDiastolic,\tPulse,\tIrregular heartbeat,\tMissed medication,\t"
          "Dizzy / Light-headed,\tWeight [kg],\tTemperature [Celsius],\tBlood Glucose [mg/dL],\t"
          "Oxygen Saturation [%],\tLocation,\tPosture,\tComment,\tTags,\t\r\n")
ROWS = [
    "2026-1-24 06:36:00,\t 24 January 2026 6:36,\t 114.0,\t 80.0,\t 70.0,\t ,\t ,\t ,\t 96.3,\t ,\t ,\t ,\t "
    "\"Left Arm\",\t \"Seated\",\t \"No cofee\",\t ,\t \r\n",
    "2026-2-10 05:04:00,\t 10 February 2026 5:04,\t 102.0,\t 72.0,\t 68.0,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t \r\n",
    "2026-2-10 05:04:00,\t 10 February 2026 5:04,\t 101.0,\t 72.0,\t 66.0,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t \r\n",
]
LATER = ("2026-3-01 07:10:00,\t 1 March 2026 7:10,\t 120.0,\t 78.0,\t 64.0,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t "
         "\"Left Arm\",\t \"Seated\",\t \"after coffee, short walk\",\t ,\t \r\n")


def export(folder: Path, name: str, rows) -> Path:
    path = folder / name
    path.write_bytes((HEADER + "".join(rows)).encode())
    return path


class ShapeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def handle(self, payload):
        return run_plugin(BP, {"command": "handle", "config": {"person_id": "person-a"},
                               "event": {"type": "bp.export", "payload": payload}})

    def payloads(self, rows):
        path = export(self.dir, "BloodPressure_10-October-2026", rows)
        r = self.handle({"path": str(path), "change_type": "created"})
        self.assertEqual(r["status"], "ok", r)
        return [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]

    def test_readings_sharing_a_timestamp_are_told_apart_by_their_ordinal(self):
        p = self.payloads(ROWS)
        self.assertEqual([(x["date_excel"], x["reading"]) for x in p],
                         [("2026-1-24 06:36:00", "1"), ("2026-2-10 05:04:00", "1"), ("2026-2-10 05:04:00", "2")])
        self.assertEqual([x["systolic"] for x in p], ["114.0", "102.0", "101.0"])

    def test_values_are_the_exports_own_strings_and_empty_cells_are_absent(self):
        first = self.payloads(ROWS)[0]
        self.assertEqual(first, {
            "date_excel": "2026-1-24 06:36:00", "date": "24 January 2026 6:36", "systolic": "114.0",
            "diastolic": "80.0", "pulse": "70.0", "weight_kg": "96.3", "location": "Left Arm",
            "posture": "Seated", "comment": "No cofee", "reading": "1",
        })

    def test_a_quoted_comma_stays_in_its_field(self):
        later = self.payloads(ROWS + [LATER])[-1]
        self.assertEqual(later["comment"], "after coffee, short walk")
        self.assertEqual(later["location"], "Left Arm")

    def test_a_deleted_export_is_nothing_to_send(self):
        r = self.handle({"path": str(self.dir / "BloodPressure_gone"), "change_type": "deleted"})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"], [])

    def test_a_missing_export_or_a_row_without_its_timestamp_is_not_retried(self):
        cases = [
            ("missing", self.dir / "BloodPressure_missing", "no export"),
            ("no date_excel", export(self.dir, "BloodPressure_bad", [",\t 1 March 2026,\t 120.0,\t 78.0\r\n"]),
             "row 2 has no date_excel"),
        ]
        for name, path, want in cases:
            with self.subTest(name):
                r = self.handle({"path": str(path), "change_type": "created"})
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"])
                self.assertIn(want, r["error"])

    def test_poll_sends_every_export_under_export_dir_and_nothing_else(self):
        export(self.dir, "BloodPressure_1", ROWS)
        (self.dir / "sub").mkdir()
        export(self.dir / "sub", "BloodPressure_2", ROWS + [LATER])
        (self.dir / "notes.txt").write_text("not an export")
        r = run_plugin(BP, {"command": "poll", "config": {"person_id": "person-a", "export_dir": str(self.dir)}})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual([e["payload"]["batch"] for e in r["events"]], ["BloodPressure_1 1/1", "BloodPressure_2 1/1"])
        self.assertEqual(sum(len(e["payload"]["envelopes"]) for e in r["events"]), 7)


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
class AgainstBuiltInWorkerTest(unittest.TestCase):
    """The importer takes over the built-in worker's facets: the same export through
    both is the same facets, so cut-over admits nothing and supersedes nothing."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        first = export(self.dir, "BloodPressure_24-February-2026", ROWS)
        self.daemon = Daemon("bp-csv", ["health.blood-pressure"], imports=[("bp-csv", first)])
        self.first = first

    def tearDown(self):
        self.daemon.close()
        self.tmp.cleanup()

    def send(self, path):
        shaped = run_plugin(BP, {"command": "handle", "config": {"person_id": "person-a"},
                                 "event": {"type": "bp.export", "payload": {"path": str(path), "change_type": "created"}}})
        self.assertEqual(shaped["status"], "ok", shaped)
        outcomes = {}
        for ev in shaped["events"]:
            r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                    "config": {"anam_url": self.daemon.url, "token_secret": "anam_importer_token_test"},
                                    "secrets": {"anam_importer_token_test": self.daemon.token}})
            self.assertEqual(r["status"], "ok", r)
            for outcome, n in r["events"][0]["payload"]["outcomes"].items():
                outcomes[outcome] = outcomes.get(outcome, 0) + n
        return outcomes

    def test_the_worker_s_export_through_the_importer_is_all_no_op(self):
        self.assertEqual(self.send(self.first), {"no-op": 3})

    def test_a_later_overlapping_export_admits_only_its_new_reading(self):
        later = export(self.dir, "BloodPressure_10-March-2026", ROWS + [LATER])
        self.assertEqual(self.send(later), {"admitted": 1, "no-op": 3})
        self.assertEqual(self.send(later), {"no-op": 4})


if __name__ == "__main__":
    unittest.main()
