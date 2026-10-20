"""The one-off extractors under records/extract (anam card 58): each turns an export into
a records file, deterministically. Synthetic exports only."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

import yaml

from tests.helpers import REPO

EXTRACT = REPO / "records" / "extract"
RECORDS = REPO / "records" / "run.py"


def module(name: str):
    spec = importlib.util.spec_from_file_location(f"extract_{name}", EXTRACT / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def workbook(path: Path, rows: list) -> Path:
    """A one-sheet .xlsx whose text cells go through shared strings, as Fitbit's do."""
    strings: list = []
    cells = []
    for r, row in enumerate(rows, start=1):
        out = []
        for col, value in row.items():
            if isinstance(value, str):
                strings.append(value)
                out.append(f'<c r="{col}{r}" t="s"><v>{len(strings) - 1}</v></c>')
            else:
                out.append(f'<c r="{col}{r}"><v>{value}</v></c>')
        cells.append(f'<row r="{r}">{"".join(out)}</row>')
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/sharedStrings.xml", "<sst>" + "".join(f"<si><t>{s}</t></si>" for s in strings) + "</sst>")
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet><sheetData>{''.join(cells)}</sheetData></worksheet>")
    return path


def records_of(out_dir: str) -> list:
    """What anam_records reads from the records files in out_dir."""
    rec = importlib.util.module_from_spec(spec := importlib.util.spec_from_file_location("records_run", RECORDS))
    spec.loader.exec_module(rec)
    return [rec.envelope(r, "p", "x") for f in sorted(Path(out_dir).glob("*.yaml")) for r in rec.records_file(f)]


class FitbitWeight(unittest.TestCase):
    def test_weights_with_a_reweigh_in_one_minute(self):
        fw = module("fitbit_weight")
        with tempfile.TemporaryDirectory() as d:
            p = workbook(Path(d) / "Weight Logs.xlsx", [
                {"A": "January 5, 2001 at 06:15AM", "B": 70.0, "C": "kilograms", "D": 22.1},
                {"A": "January 5, 2001 at 06:15AM", "B": 69.9, "C": "kilograms"},
                {"A": "February 3, 2001 at 07:40PM", "B": 71.75, "C": "kilograms", "D": 22.5}])
            doc = fw.extract(p)
            self.assertEqual(doc, fw.extract(p))
        ids = [r["id"] for r in doc["records"]]
        self.assertEqual(ids, ["fitbit:2001-01-05T06:15", "fitbit:2001-01-05T06:15:2", "fitbit:2001-02-03T19:40"])
        self.assertEqual(doc["records"][0]["bmi"], 22.1)
        self.assertNotIn("bmi", doc["records"][1])
        self.assertEqual(doc["records"][2]["date"], "2001-02-03 19:40")

    def test_another_unit_stops_it(self):
        fw = module("fitbit_weight")
        with tempfile.TemporaryDirectory() as d:
            p = workbook(Path(d) / "w.xlsx", [{"A": "January 5, 2001 at 06:15AM", "B": 154.0, "C": "pounds"}])
            with self.assertRaises(SystemExit):
                fw.extract(p)


class FitbitSleep(unittest.TestCase):
    ROW = {"A": "June 3, 2001 at 10:30PM", "B": "6h 0m", "C": 21600.0, "D": "0m", "E": 0.0, "F": "30m",
           "G": 1800.0, "H": 2.0, "I": 9.0, "J": "2m", "K": 120.0, "L": "June 4, 2001 at 05:00AM"}

    def test_a_sleep_is_an_ieee_episode_in_utc(self):
        fs = module("fitbit_sleep")
        with tempfile.TemporaryDirectory() as d:
            doc = fs.extract(workbook(Path(d) / "Sleep Logs.xlsx", [self.ROW]), "Pacific/Auckland")
        (r,) = doc["records"]
        self.assertEqual(r["id"], "fitbit:sleep:2001-06-03T22:30")
        self.assertEqual(r["effective_time_frame"]["time_interval"],
                         {"start_date_time": "2001-06-03T10:30:00Z", "end_date_time": "2001-06-03T17:00:00Z"})
        self.assertEqual(r["total_sleep_time"], {"value": 360, "unit": "min"})
        self.assertEqual(r["wake_after_sleep_onset"], {"value": 30, "unit": "min"})
        self.assertEqual((r["awake_count"], r["restless_count"], r["restless_minutes"]), (2, 9, 2))
        self.assertNotIn("is_main_sleep", r)

    def test_columns_that_do_not_fill_the_interval_stop_it(self):
        fs = module("fitbit_sleep")
        with tempfile.TemporaryDirectory() as d:
            p = workbook(Path(d) / "s.xlsx", [{**self.ROW, "G": 1860.0}])
            with self.assertRaises(SystemExit) as ctx:
                fs.extract(p, "UTC")
        self.assertIn("do not fill", str(ctx.exception))

    def test_the_records_file_reads_back_through_anam_records(self):
        with tempfile.TemporaryDirectory() as d:
            p = workbook(Path(d) / "Sleep Logs.xlsx", [self.ROW])
            subprocess.run([sys.executable, str(EXTRACT / "fitbit_sleep.py"), "--out-dir", d, "--zone", "UTC", str(p)],
                           check=True, capture_output=True)
            (env,) = records_of(d)
        self.assertEqual(env["type"], "health.sleep-episode")
        self.assertEqual(env["payload"]["total_sleep_time"], {"value": 360, "unit": "min"})


STRONG = ("Date;Workout Name;Duration (sec);Exercise Name;Set Order;Weight (kg);Reps;Distance (meters);"
          "Seconds;Notes;Workout Notes;RPE\n"
          "2001-07-02 17:30:00;Legs;3600;Squat;1;60;8;;;;felt good;\n"
          "2001-07-02 17:30:00;Legs;3600;Squat;2;62.5;6;;;slow;;8\n"
          "2001-07-04 06:00:00;Pull;200000;Row;1;40;10;;;;;\n")


class Strong(unittest.TestCase):
    def test_workouts_with_a_capped_duration(self):
        sc = module("strong_csv")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "strong1.csv"
            p.write_text(STRONG)
            doc, rows = sc.extract(p, "UTC")
        self.assertEqual(rows, 3)
        legs, pull = doc["records"]
        self.assertEqual(legs["id"], "strong:session:2001-07-02T17:30:00")
        self.assertEqual(legs["effective_time_frame"]["time_interval"]["duration"], {"value": 3600, "unit": "sec"})
        self.assertNotIn("duration_capped", legs)
        self.assertEqual(legs["sets"][1], {"exercise": "Squat", "set": "2", "kg": 62.5, "reps": 6, "rpe": 8,
                                           "note": "slow"})
        self.assertEqual(legs["workout_notes"], ["felt good"])
        self.assertTrue(pull["duration_capped"])
        self.assertEqual(pull["effective_time_frame"]["time_interval"]["duration"]["value"], 3 * 3600)
        self.assertEqual(pull["reported_duration_sec"], 200000)

    def test_max_session_sec_moves_the_cap(self):
        sc = module("strong_csv")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "strong1.csv"
            p.write_text(STRONG)
            doc, _ = sc.extract(p, "UTC", 1800)
        legs, pull = doc["records"]
        self.assertTrue(legs["duration_capped"])
        self.assertEqual(legs["effective_time_frame"]["time_interval"]["duration"]["value"], 1800)
        self.assertEqual(legs["reported_duration_sec"], 3600)
        self.assertEqual(pull["effective_time_frame"]["time_interval"]["duration"]["value"], 1800)


def technogym_zip(path: Path, sessions: list) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("export/indooractivities-1.json", json.dumps(sessions))
    return path


SESSION = {"on": "2001-03-04T10:15:00+11:00", "phId": "ph-1", "facility": "Gym",
           "performedData": {"pr": [{"n": "Duration", "v": 1200}, {"n": "RowingDistance", "v": 4000.0},
                                    {"n": "AvgSpm", "v": 24}, {"n": "Mets", "v": 427}, {"n": "AvgHr", "v": 140}],
                             "st": [{"pos": 1, "pr": [{"n": "Duration", "v": 600}, {"n": "RowingDistance", "v": 2000}]}]}}


class Technogym(unittest.TestCase):
    def run_it(self, sessions):
        with tempfile.TemporaryDirectory() as d:
            p = technogym_zip(Path(d) / "export.zip", sessions)
            r = subprocess.run([sys.executable, str(EXTRACT / "technogym_json.py"), "--out-dir", d, str(p)],
                               capture_output=True, text=True)
            files = list(Path(d).glob("technogym.*.yaml"))
            return r, (yaml.safe_load(files[0].read_text()) if files else None)

    def test_a_rowing_session_starts_its_duration_before_on(self):
        r, doc = self.run_it([SESSION])
        self.assertEqual(r.returncode, 0, r.stderr)
        (s,) = doc["records"]
        self.assertEqual(s["id"], "technogym:2001-03-04T10:15:00+11:00")
        self.assertEqual(s["activity_name"], "rowing.machine")
        self.assertEqual(s["effective_time_frame"]["time_interval"]["start_date_time"], "2001-03-04T09:55:00+11:00")
        self.assertEqual(s["distance"], {"value": 4000, "unit": "m"})
        self.assertEqual(s["avg_hr_bpm"], 140)
        self.assertNotIn("mets", s)
        self.assertEqual(s["splits"], [{"position": 1, "duration_sec": 600, "distance_m": 2000}])

    def test_an_unknown_measure_stops_it(self):
        odd = json.loads(json.dumps(SESSION))
        odd["performedData"]["pr"].append({"n": "Watts2", "v": 1})
        r, doc = self.run_it([odd])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unknown measure 'Watts2'", r.stderr)
        self.assertIsNone(doc)


REPORT = """\
  PATIENT: A PERSON                Lab REF: 26-12345678-ABC
  REFERRED: 01/02/2001   COLLECTED: 02/02/2001 09:10   REPORTED: 02/02/2001 14:00

  GENERAL CHEMISTRY                                  SPECIMEN: Serum
        Date:        05/06/00       02/02/01
        Time:        08:20          09:10
  Lab Number:        11111111       12345678
  ------------------------------------------------------------
  Sodium                  140            137     (135-145)   mmol/L
  Potassium               4.1           *5.6     (3.5-5.2)   mmol/L

  12345678: Repeat in three months.
"""


class Pathology(unittest.TestCase):
    def test_a_report_s_own_draw_and_its_history_columns(self):
        acl = module("acl_pathology")
        hdr, lab, panel, specimen, results, comment, fasting = acl.parse_report(REPORT)
        self.assertEqual((lab, panel, specimen), ("12345678", "GENERAL CHEMISTRY", "Serum"))
        self.assertEqual(hdr["collected"], "02/02/2001 09:10")
        own = [r for r in results if r["lab"] == lab]
        self.assertEqual([(r["analyte"], r["value"]) for r in own], [("Sodium", "137"), ("Potassium", "5.6")])
        self.assertTrue(own[1]["flagged"])
        self.assertEqual(own[0]["range"], "135-145")
        self.assertEqual(own[0]["date"], "2001-02-02")
        self.assertEqual([r["value"] for r in results if r["lab"] == "11111111"], ["140", "4.1"])
        self.assertEqual(comment, "Repeat in three months.")


class BloodPressureDiary(unittest.TestCase):
    def test_rows_are_reshaped_to_the_omh_body_and_others_pass(self):
        src = {"document": {"name": "diary.pdf"}, "extracted": {"method": "hand", "version": 1},
               "records": [{"type": "health.blood-pressure", "id": "2001-05-06 07:00:00/1",
                            "date_excel": "2001-05-06 07:00:00", "reading": "1", "systolic": "131",
                            "diastolic": "81.5", "posture": "Seated", "comment": "am"},
                           {"type": "record.edge", "id": "n"}]}
        with tempfile.TemporaryDirectory() as d:
            i, o = Path(d) / "in.yaml", Path(d) / "out.yaml"
            i.write_text(yaml.safe_dump(src, sort_keys=False))
            subprocess.run([sys.executable, str(EXTRACT / "bp_diary_omh.py"), "Asia/Tokyo", str(i), str(o)],
                           check=True, capture_output=True)
            out = yaml.safe_load(o.read_text())
        bp, note = out["records"]
        self.assertEqual(bp["systolic_blood_pressure"], {"value": 131.0, "unit": "mmHg"})
        self.assertEqual(bp["diastolic_blood_pressure"], {"value": 81.5, "unit": "mmHg"})
        self.assertEqual(bp["body_posture"], "sitting")
        self.assertEqual(bp["effective_time_frame"], {"date_time": "2001-05-06T07:00:00+09:00"})
        self.assertNotIn("systolic", bp)
        self.assertEqual(note, {"type": "record.edge", "id": "n"})
        self.assertEqual(out["extracted"]["version"], 2)


class Retype(unittest.TestCase):
    def test_a_note_is_retyped_by_the_table_and_a_rerun_changes_nothing(self):
        notes = "records:\n  - type: record.note  # kept\n    id: n-1\n  - {type: health.weight, id: w-1}\n"
        table = {"renames": [{"from": "record.note", "to": "record.edge"}]}
        with tempfile.TemporaryDirectory() as d:
            f, t = Path(d) / "notes.yaml", Path(d) / "record-edge.json"
            f.write_text(notes)
            t.write_text(json.dumps(table))
            cmd = [sys.executable, "-I", str(EXTRACT / "retype_records.py"), "--table", str(t)]
            dry = subprocess.run(cmd + [d], check=True, capture_output=True, text=True)
            self.assertEqual(f.read_text(), notes)
            self.assertIn("1  record.note -> record.edge", dry.stdout)
            subprocess.run(cmd + ["--yes", d], check=True, capture_output=True)
            self.assertEqual(f.read_text(), notes.replace("type: record.note", "type: record.edge"))
            again = subprocess.run(cmd + ["--yes", d], check=True, capture_output=True, text=True)
            self.assertIn("0 file(s) rewritten", again.stdout)


if __name__ == "__main__":
    unittest.main()
