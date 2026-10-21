"""anam_records: records files read as Anam's built-in records worker read them, and
a cut-over from the worker that is all no-op."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

PLUGIN = REPO / "records" / "run.py"
SUBMIT = REPO / "anam_submit" / "run.py"

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("records_run", PLUGIN)
records = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(records)

# LABS holds the scalars where Python's YAML and Go's yaml.v3 disagree, in fields
# the strict Definitions admit.
LABS = """\
document: {name: report.pdf, sha256: abc}
extracted: {method: hand, version: 1}
records:
  - type: health.lab-result
    id: acl:10000001/sodium
    collected: 2001-02-02 09:10
    analyte: Sodium
    value: "137"
    value_num: 137.0
    unit: mmol/L
    lab_number: "10000001"
    fasting: true
  - type: health.lab-result
    id: 20240916
    collected: 2024-09-16 07:15
    analyte: "Ferritin: serum"
    value: '1,000'
    value_num: 1_000.50
    lab_number: '0777'
    note: |
      two lines,
      kept
"""

# WEIGHTS holds the note beside the weights. record.edge v2 requires source_time, and the
# offset in it is what places the note: the note was written in Australia/Sydney, which
# kept +10:00 on 2 October 2026.
WEIGHTS = """\
records:
  - {type: health.weight, id: 0777, date: 2026-10-01 07:00, kg: 80.0, bmi: 24.10}
  - {type: health.weight, id: w-2, date: 2026-10-02 07:00, kg: 82.5e0, logged_as: yes}
  - type: record.edge
    id: n-1
    at: 2026-10-02 08:00
    source_time: {value: 2026-10-02 08:00, zone: Australia/Sydney, offset: "+10:00", basis: source}
    about: [0b6f2a52-3c1e-4d7a-9f00-1a2b3c4d5e6f, "1c6f2a52-3c1e-4d7a-9f00-1a2b3c4d5e6f"]
    text: ~not null
"""

FLIGHTS = """{"records": [{"type": "place.trip.flight", "id": "f-1", "date": "2026-10-03 +10:00", "trip": "t",
  "from": "SYD", "to": "MEL", "flight": "QF 400"}]}
"""


def folder(files: dict) -> tempfile.TemporaryDirectory:
    d = tempfile.TemporaryDirectory()
    for name, text in files.items():
        (Path(d.name) / name).write_text(text)
    return d


def run(command: str, records_dir: str) -> dict:
    return run_plugin(PLUGIN, {"command": command, "config": {"records_dir": records_dir, "person_id": "person-a"}})


class Scalars(unittest.TestCase):
    def test_plain_scalars_resolve_as_yaml_v3_resolves_them(self):
        cases = {"yes": "yes", "on": "on", "no": "no", "True": True, "FALSE": False, "~": None, "": None,
                 "Null": None, "0777": 511, "0x1F": 31, "0o17": 15, "0b101": 5, "-0b101": -5, "1_000": 1000,
                 "+5": 5, "08": 8.0, "1e3": 1000.0, ".5": 0.5, "12:30": "12:30", "2026-01-30": "2026-01-30",
                 "1.2.3": "1.2.3", "9223372036854775808": 9223372036854775808.0, "-": "-", ".": "."}
        for text, want in cases.items():
            with self.subTest(text=text):
                got = records.resolve(text)
                self.assertEqual(got, want)
                self.assertIs(type(got), type(want))

    def test_floats_are_written_as_go_writes_them(self):
        cases = {137.0: "137", 1000.5: "1000.5", 0.1: "0.1", -0.0: "-0", 1e21: "1e+21", 1.5e22: "1.5e+22",
                 1e-7: "1e-07".replace("e-07", "e-7"), 0.000001: "0.000001", 1e20: "100000000000000000000"}
        for f, want in cases.items():
            with self.subTest(f=f):
                self.assertEqual(records.go_float(f), want)

    def test_a_number_python_would_write_differently_is_refused(self):
        self.assertEqual(records.number(137.0, "x"), 137)
        self.assertEqual(records.number(1000.5, "x"), 1000.5)
        for f in (0.00001, 1e-7, -0.0000123):
            with self.subTest(f=f), self.assertRaises(records.BadRecords):
                records.number(f, "x")

    def test_nan_and_infinity_are_refused(self):
        for text in (".nan", ".inf", "-.Inf"):
            with self.subTest(text=text), self.assertRaises(records.BadRecords):
                records.resolve(text)


class Files(unittest.TestCase):
    def test_records_become_envelopes_with_the_payload_the_worker_made(self):
        with folder({"a-labs.yaml": LABS, "b-weights.yml": WEIGHTS, "c-flights.json": FLIGHTS,
                     "notes.txt": "not records"}) as d:
            paths, envs = records.scan({"records_dir": d}, "person-a")
        self.assertEqual([p.name for p in paths], ["a-labs.yaml", "b-weights.yml", "c-flights.json"])
        sodium, ferritin, w1, w2, note, flight = envs
        self.assertEqual(sodium["type"], "health.lab-result")
        self.assertNotIn("type", sodium["payload"])
        self.assertNotIn("definition_version", sodium)
        self.assertEqual(sodium["asserted_person"], "person-a")
        self.assertEqual(sodium["payload"]["collected"], "2001-02-02 09:10")
        self.assertEqual(sodium["payload"]["value_num"], 137)
        self.assertIs(sodium["payload"]["fasting"], True)
        self.assertEqual(ferritin["payload"]["id"], "20240916")
        self.assertEqual(ferritin["payload"]["value_num"], 1000.5)
        self.assertEqual(ferritin["payload"]["lab_number"], "0777")
        self.assertEqual(ferritin["payload"]["note"], "two lines,\nkept\n")
        self.assertEqual(w1["payload"]["id"], "511")
        self.assertEqual(w1["payload"]["date"], "2026-10-01 07:00")
        self.assertEqual(w2["payload"]["kg"], 82.5)
        self.assertEqual(w2["payload"]["logged_as"], "yes")
        self.assertEqual(note["payload"]["about"], ["0b6f2a52-3c1e-4d7a-9f00-1a2b3c4d5e6f", "1c6f2a52-3c1e-4d7a-9f00-1a2b3c4d5e6f"])
        self.assertEqual(note["payload"]["text"], "~not null")
        self.assertEqual(flight["payload"]["flight"], "QF 400")

    def test_a_poll_is_one_snapshot_of_the_types_it_carries(self):
        with folder({"a.yaml": LABS, "b.yaml": WEIGHTS}) as d:
            r = run("poll", d)
        self.assertEqual(r["status"], "ok", r)
        parts = [ev["payload"]["snapshot"] for ev in r["events"]]
        self.assertEqual(len({p["id"] for p in parts}), 1)
        self.assertEqual(parts[0]["types"], ["health.lab-result", "health.weight", "record.edge"])

    def test_bad_files_are_refused_and_named(self):
        cases = {
            "unknown field": "records: [{type: a.b, id: x}]\nsource: y\n",
            "no records": "document: {name: x}\n",
            "empty records": "records: []\n",
            "repeated key": "records: [{type: a.b, id: x, v: 1, v: 2}]\n",
            "no id": "records: [{type: a.b, v: 1}]\n",
            "empty id": "records: [{type: a.b, id: ''}]\n",
            "no type": "records: [{id: x}]\n",
            "not a mapping": "records: [x]\n",
            "explicit tag": "records: [{type: a.b, id: !!int '5'}]\n",
        }
        for name, text in cases.items():
            with self.subTest(name), folder({"bad.yaml": text}) as d:
                r = run("poll", d)
                self.assertEqual(r["status"], "error", r)
                self.assertIn("bad.yaml", r["error"])
                self.assertFalse(r["retry"])

    def test_two_records_claiming_one_identity_are_refused_across_files_and_types(self):
        one = "records: [{type: health.lab-result, id: x}]\n"
        other = "records: [{type: health.weight, id: x}]\n"
        with folder({"a.yaml": one, "b.yaml": other}) as d:
            r = run("poll", d)
        self.assertEqual(r["status"], "error")
        self.assertIn("a.yaml record 1 and b.yaml record 1 both declare the row x", r["error"])

    def test_blood_pressure_identity_is_its_time_and_reading(self):
        bp = ("records:\n"
              "  - {type: health.blood-pressure, id: a, date_excel: '2026-10-01 08:00:00', reading: 1}\n"
              "  - {type: health.blood-pressure, id: b, date_excel: '2026-10-01 08:00:00', reading: 1}\n")
        with folder({"bp.yaml": bp}) as d:
            r = run("poll", d)
        self.assertIn("both declare the row 2026-10-01 08:00:00/1", r["error"])

    def test_a_missing_folder_is_not_retried(self):
        r = run("poll", "/nonexistent/records")
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["retry"])

    def test_handle_resends_the_whole_folder(self):
        with folder({"a.yaml": LABS}) as d:
            r = run_plugin(PLUGIN, {"command": "handle", "config": {"records_dir": d, "person_id": "p"},
                                    "event": {"payload": {"path": f"{d}/a.yaml", "change_type": "deleted"}}})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(sum(len(ev["payload"]["envelopes"]) for ev in r["events"]), 2)


TYPES = ["health.lab-result", "health.weight", "record.edge", "place.trip.flight"]


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
class CutOver(unittest.TestCase):
    def submit(self, daemon: Daemon, events: list) -> dict:
        outcomes: dict = {}
        for ev in events:
            r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                    "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                    "secrets": {"anam_importer_token_test": daemon.token}})
            self.assertEqual(r["status"], "ok", r)
            for o, n in r["events"][0]["payload"]["outcomes"].items():
                outcomes[o] = outcomes.get(o, 0) + n
            self.last = r
        return outcomes

    def test_every_record_the_worker_admitted_resends_as_no_op(self):
        with folder({"a-labs.yaml": LABS, "b-weights.yml": WEIGHTS, "c-flights.json": FLIGHTS}) as d:
            daemon = Daemon("records", TYPES, imports=[("records", Path(d))])
            try:
                shaped = run("poll", d)
                self.assertEqual(self.submit(daemon, shaped["events"]), {"no-op": 6})
                self.assertIn("0 of 6 live absent", self.last["result"])

                # A record removed from its file is reported absent, never retracted;
                # a changed one supersedes.
                lines = WEIGHTS.replace("kg: 80.0", "kg: 80.5").splitlines(keepends=True)
                (Path(d) / "b-weights.yml").write_text("".join(l for l in lines if "w-2, date" not in l))
                self.assertEqual(self.submit(daemon, run("poll", d)["events"]), {"no-op": 4, "superseded": 1})
                self.assertIn("1 of 6 live absent", self.last["result"])
            finally:
                daemon.close()


if __name__ == "__main__":
    unittest.main()
