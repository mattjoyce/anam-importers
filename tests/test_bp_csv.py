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
    "2001-1-24 06:36:00,\t 24 January 2001 6:36,\t 117.0,\t 77.0,\t 63.0,\t ,\t ,\t ,\t 88.8,\t ,\t ,\t ,\t "
    "\"Left Arm\",\t \"Seated\",\t \"No cofee\",\t ,\t \r\n",
    "2001-2-10 05:04:00,\t 10 February 2001 5:04,\t 105.0,\t 72.0,\t 61.0,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t \r\n",
    "2001-2-10 05:04:00,\t 10 February 2001 5:04,\t 104.0,\t 72.0,\t 59.0,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t \r\n",
]
LATER = ("2026-3-01 07:10:00,\t 1 March 2026 7:10,\t 120.0,\t 78.0,\t 64.0,\t ,\t ,\t ,\t ,\t ,\t ,\t ,\t "
         "\"Left Arm\",\t \"Seated\",\t \"after coffee, short walk\",\t ,\t \r\n")
# A reading with every column the app can fill, the checkboxes ticked (anam card 97).
EVERY_COLUMN = ("2026-3-02 07:15:00,\t 2 March 2026 7:15,\t 131.0,\t 84.0,\t 72.0,\t \"Yes\",\t \"Yes\",\t \"Yes\",\t "
                "96.1,\t 36.8,\t 104.0,\t 97.0,\t \"Left Arm\",\t \"Seated\",\t \"woke early\",\t \"stress, travel\",\t \r\n")


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
                         [("2001-1-24 06:36:00", "1"), ("2001-2-10 05:04:00", "1"), ("2001-2-10 05:04:00", "2")])
        self.assertEqual([x["systolic_blood_pressure"]["value"] for x in p], [117.0, 105.0, 104.0])

    def test_a_reading_is_the_omh_body_beside_the_export_s_own_text(self):
        first = self.payloads(ROWS)[0]
        self.assertEqual(first, {
            "systolic_blood_pressure": {"value": 117.0, "unit": "mmHg"},
            "diastolic_blood_pressure": {"value": 77.0, "unit": "mmHg"},
            "effective_time_frame": {"date_time": "2001-01-24T06:36:00+11:00"},
            "body_posture": "sitting",
            "date_excel": "2001-1-24 06:36:00", "date": "24 January 2001 6:36", "pulse": "63.0",
            "weight_kg": "88.8", "location": "Left Arm", "comment": "No cofee", "reading": "1",
            # No zone key: the Definition's zone, an assumption (anam card 198).
            "source_time": {"value": "2001-1-24 06:36:00", "zone": "Australia/Sydney", "basis": "assumption"},
        })

    def test_the_zone_key_makes_the_cuff_s_zone_configuration_and_only_the_definition_s_is_taken(self):
        path = export(self.dir, "BloodPressure_10-October-2026", ROWS)
        event = {"type": "bp.export", "payload": {"path": str(path), "change_type": "created"}}

        def run(config):
            return run_plugin(BP, {"command": "handle", "config": {"person_id": "person-a", **config}, "event": event})

        assumed = run({})
        self.assertTrue(any("basis assumption" in line["message"] for line in assumed["logs"]), assumed["logs"])
        named = run({"zone": "Australia/Sydney"})
        self.assertEqual(named["status"], "ok", named)
        envs = [e["payload"] for ev in named["events"] for e in ev["payload"]["envelopes"]]
        self.assertEqual({e["source_time"]["basis"] for e in envs}, {"configuration"})
        self.assertEqual(envs[0]["effective_time_frame"]["date_time"], "2001-01-24T06:36:00+11:00")
        self.assertFalse(any("basis assumption" in line["message"] for line in named["logs"]), named["logs"])
        # The Definition reads date_excel in Sydney, so a cuff set to London cannot be
        # placed truly yet; a misspelt zone is no zone.
        for zone, want in (("Europe/London", "anam card 198"), ("Europe/Londn", "not an IANA zone"), ("Local", "no zone")):
            with self.subTest(zone):
                r = run({"zone": zone})
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"])
                self.assertIn("config zone", r["error"])
                self.assertIn(want, r["error"])

    def test_a_wall_clock_sydney_skips_or_repeats_is_left_out_and_poll_is_no_snapshot(self):
        # Card 197's acceptance example 4: 02:30 on 4 October 2026 never happened in
        # Sydney, and 02:30 on 5 April 2026 happened twice.
        gap = ROWS[1].replace("2001-2-10 05:04:00", "2026-10-4 02:30:00")
        overlap = ROWS[1].replace("2001-2-10 05:04:00", "2026-4-5 02:30:00")
        export(self.dir, "BloodPressure_10-October-2026", [ROWS[0], gap, overlap])
        r = run_plugin(BP, {"command": "poll", "config": {"person_id": "person-a", "export_dir": str(self.dir)}})
        self.assertEqual(r["status"], "ok", r)
        sent = [e["payload"]["date_excel"] for ev in r["events"] for e in ev["payload"]["envelopes"]]
        self.assertEqual(sent, ["2001-1-24 06:36:00"])
        messages = " | ".join(line["message"] for line in r["logs"])
        self.assertIn("2026-10-4 02:30:00 #1", messages)
        self.assertIn("skip", messages)
        self.assertIn("twice", messages)
        self.assertNotIn("snapshot", r["events"][0]["payload"])
        self.assertIn("no snapshot", r["result"])

    def test_an_export_with_no_date_in_its_name_is_dated_by_mtime_in_the_cuff_s_zone_not_the_host_s(self):
        import importlib.util
        import time

        spec = importlib.util.spec_from_file_location("bp_csv_run_mtime", BP)
        bp = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bp)
        path = export(self.dir, "BloodPressure_undated", ROWS)
        # 2026-10-20T14:30:00Z is 21 October in Sydney and 20 October in London and UTC.
        when = 1792506600
        os.utime(path, (when, when))
        before = os.environ.get("TZ")
        try:
            for host in ("UTC", "Europe/London", "America/Los_Angeles"):
                with self.subTest(host):
                    os.environ["TZ"] = host
                    time.tzset()
                    self.assertEqual(bp.exported_on(path).isoformat(), "2026-10-21")
        finally:
            if before is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = before
            time.tzset()

    def test_a_posture_nobody_has_named_stops_the_run(self):
        row = ROWS[0].replace('"Seated"', '"Reclined"')
        path = export(self.dir, "BloodPressure_reclined", [row])
        r = self.handle({"path": str(path), "change_type": "created"})
        self.assertEqual(r["status"], "error", r)
        self.assertFalse(r["retry"])
        self.assertIn("posture", r["error"])

    def test_a_quoted_comma_stays_in_its_field(self):
        later = self.payloads(ROWS + [LATER])[-1]
        self.assertEqual(later["comment"], "after coffee, short walk")
        self.assertEqual(later["location"], "Left Arm")

    def test_every_column_the_app_can_fill_is_kept_as_written(self):
        p = self.payloads(ROWS + [EVERY_COLUMN])[-1]
        self.assertEqual({k: p[k] for k in ("irregular_heartbeat", "missed_medication", "dizzy_light_headed",
                                            "temperature_celsius", "blood_glucose_mg_dl", "oxygen_saturation_pct",
                                            "tags")},
                         {"irregular_heartbeat": "Yes", "missed_medication": "Yes", "dizzy_light_headed": "Yes",
                          "temperature_celsius": "36.8", "blood_glucose_mg_dl": "104.0",
                          "oxygen_saturation_pct": "97.0", "tags": "stress, travel"})

    def test_a_deleted_export_is_nothing_to_send(self):
        r = self.handle({"path": str(self.dir / "BloodPressure_gone"), "change_type": "deleted"})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"], [])

    def test_a_missing_export_or_a_row_without_its_timestamp_is_not_retried(self):
        cases = [
            ("missing", self.dir / "BloodPressure_missing", "no export"),
            ("no date_excel", export(self.dir, "BloodPressure_bad", [",\t" + ROWS[1].split(",", 1)[1]]),
             "line 2 has no date_excel"),
        ]
        for name, path, want in cases:
            with self.subTest(name):
                r = self.handle({"path": str(path), "change_type": "created"})
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"])
                self.assertIn(want, r["error"])

    def test_an_export_whose_records_cannot_be_told_apart_sends_nothing(self):
        # The blue team's case (anam card 114): the first comment lost its closing
        # quote, so under the worker's LazyQuotes it swallowed the next reading, and a
        # poll claimed a complete snapshot without it.
        unclosed = [LATER.replace('"after coffee, short walk"', '"after coffee, short walk'),
                    ROWS[0].replace("2001-1-24", "2026-3-02")]
        cases = {
            "unclosed quote": (unclosed, "line 2: a quoted field holds a quote, on line 3,"),
            "never closed": ([LATER.replace('"after coffee, short walk",\t ,\t \r\n', '"after coffee\r\n')],
                             "line 2: a quoted field is never closed"),
            "stray quote": ([LATER.replace('"after coffee, short walk"', '"after "coffee" walk"')],
                            "line 2: a quoted field holds a quote, on line 2,"),
            "short record": ([ROWS[0], "2026-3-03 07:00:00,\t 3 March 2026 7:00,\t 120.0,\t 80.0\r\n"],
                             "line 3 has 4 fields and the header 17"),
        }
        for name, (rows, want) in cases.items():
            with self.subTest(name):
                folder = self.dir / name.replace(" ", "-")
                folder.mkdir()
                export(folder, "BloodPressure_10-October-2026", rows)
                r = run_plugin(BP, {"command": "poll", "config": {"person_id": "p", "export_dir": str(folder)}})
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"])
                self.assertIn(want, r["error"])
                self.assertIn("nothing of it is sent", r["error"])

    def test_a_closed_multiline_field_and_doubled_quotes_still_read(self):
        row = LATER.replace('"after coffee, short walk"', '"after ""strong"" coffee,\r\nshort walk"')
        p = self.payloads([row])
        self.assertEqual(p[0]["comment"], 'after "strong" coffee,\nshort walk')
        self.assertEqual(p[0]["date_excel"], "2026-3-01 07:10:00")

    def test_poll_sends_every_export_under_export_dir_and_nothing_else(self):
        export(self.dir, "BloodPressure_1", ROWS)
        (self.dir / "sub").mkdir()
        export(self.dir / "sub", "BloodPressure_2", ROWS + [LATER])
        (self.dir / "notes.txt").write_text("not an export")
        r = run_plugin(BP, {"command": "poll", "config": {"person_id": "person-a", "export_dir": str(self.dir)}})
        self.assertEqual(r["status"], "ok", r)
        # BloodPressure_2 holds every reading BloodPressure_1 does, so each is sent once, from it.
        self.assertEqual([e["payload"]["batch"] for e in r["events"]], ["BloodPressure_2 1/1"])
        self.assertEqual(sum(len(e["payload"]["envelopes"]) for e in r["events"]), 4)

    def test_exports_go_oldest_first_by_the_date_in_their_name_and_a_reading_goes_once_from_the_newest(self):
        corrected = LATER.replace("after coffee, short walk", "after tea, short walk")
        export(self.dir, "BloodPressure_10-October-2026", ROWS + [corrected])
        export(self.dir, "BloodPressure_9-October-2026", ROWS + [LATER])
        export(self.dir, "BloodPressure_1-September-2026", ROWS[:1])
        r = run_plugin(BP, {"command": "poll", "config": {"person_id": "person-a", "export_dir": str(self.dir)}})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual([e["payload"]["batch"] for e in r["events"]], ["BloodPressure_10-October-2026 1/1"])
        sent = [e["payload"] for ev in r["events"] for e in ev["payload"]["envelopes"]]
        self.assertEqual(len(sent), 4)
        self.assertEqual(sent[-1]["comment"], "after tea, short walk")

    def test_an_older_export_dropped_late_leaves_a_newer_one_s_readings_alone(self):
        corrected = LATER.replace("after coffee, short walk", "after tea, short walk")
        export(self.dir, "BloodPressure_10-October-2026", ROWS + [corrected])
        old = export(self.dir, "BloodPressure_9-October-2026", ROWS + [LATER])
        r = run_plugin(BP, {"command": "handle", "config": {"person_id": "person-a", "export_dir": str(self.dir)},
                            "event": {"type": "bp.export", "payload": {"path": str(old), "change_type": "created"}}})
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"], [])


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
class AgainstAnamTest(unittest.TestCase):
    """Readings reach Anam as health.blood-pressure v6: an export is admitted once and
    a resend is no-op; a later export that overlaps admits only its new reading."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.daemon = Daemon("bp-csv", ["health.blood-pressure"])

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

    def test_an_export_is_admitted_once(self):
        first = export(self.dir, "BloodPressure_24-February-2026", ROWS)
        self.assertEqual(self.send(first), {"admitted": 3})
        self.assertEqual(self.send(first), {"no-op": 3})

    def test_a_later_overlapping_export_admits_only_its_new_reading(self):
        self.send(export(self.dir, "BloodPressure_24-February-2026", ROWS))
        later = export(self.dir, "BloodPressure_10-March-2026", ROWS + [LATER])
        self.assertEqual(self.send(later), {"admitted": 1, "no-op": 3})

    def test_a_correction_in_a_newer_export_stands_through_a_resend(self):
        corrected = LATER.replace("after coffee, short walk", "after tea, short walk")
        export(self.dir, "BloodPressure_9-October-2026", ROWS + [LATER])
        export(self.dir, "BloodPressure_10-October-2026", ROWS + [corrected])
        for want in ({"admitted": 4}, {"no-op": 4}):
            shaped = run_plugin(BP, {"command": "poll", "config": {"person_id": "person-a", "export_dir": str(self.dir)}})
            outcomes = {}
            for ev in shaped["events"]:
                r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                        "config": {"anam_url": self.daemon.url, "token_secret": "anam_importer_token_test"},
                                        "secrets": {"anam_importer_token_test": self.daemon.token}})
                for outcome, n in r["events"][0]["payload"]["outcomes"].items():
                    outcomes[outcome] = outcomes.get(outcome, 0) + n
            self.assertEqual(outcomes, want)

    def test_a_reading_with_every_column_filled_is_admitted(self):
        path = export(self.dir, "BloodPressure_3-March-2026", ROWS + [EVERY_COLUMN])
        self.assertEqual(self.send(path), {"admitted": 4})
        self.assertEqual(self.send(path), {"no-op": 4})

if __name__ == "__main__":
    unittest.main()
