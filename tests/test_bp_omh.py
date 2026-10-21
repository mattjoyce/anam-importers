"""The blood pressure reading as an Open mHealth body (anam card 83)."""

import importlib.util
import unittest

from tests.helpers import REPO

_spec = importlib.util.spec_from_file_location("bp_csv_run", REPO / "bp_csv" / "run.py")
bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bp)

ROW = {"date_excel": "2001-1-24 06:36:00", "date": "24 January 2001 6:36", "systolic": "117.0",
       "diastolic": "77", "pulse": "63.0", "location": "Left Arm", "posture": "Seated", "reading": "1"}


class OMHTest(unittest.TestCase):
    def test_pressures_are_numbers_in_mmhg_and_nothing_is_rounded(self):
        p = bp.omh(ROW)
        self.assertEqual(p["systolic_blood_pressure"], {"value": 117.0, "unit": "mmHg"})
        self.assertEqual(p["diastolic_blood_pressure"], {"value": 77, "unit": "mmHg"})
        self.assertNotIn("systolic", p)

    def test_the_time_carries_sydney_s_offset_for_its_date(self):
        cases = [("2001-1-24 06:36:00", "2001-01-24T06:36:00+11:00"), ("2000-5-29 05:41:00", "2000-05-29T05:41:00+10:00")]
        for local, want in cases:
            with self.subTest(local):
                self.assertEqual(bp.omh({**ROW, "date_excel": local})["effective_time_frame"]["date_time"], want)

    def test_source_time_keeps_date_excel_as_written_with_its_zone_and_basis(self):
        # Card 197's acceptance example 3: a local time with no offset names the
        # policy that read it.
        self.assertEqual(bp.omh(ROW)["source_time"],
                         {"value": "2001-1-24 06:36:00", "zone": "Australia/Sydney", "basis": "assumption"})
        named = bp.omh(ROW, bp.Clock("Australia/Sydney", "configuration"))
        self.assertEqual(named["source_time"]["basis"], "configuration")

    def test_a_wall_clock_the_zone_skips_or_repeats_is_refused(self):
        for local, word in (("2026-10-4 02:30:00", "skip"), ("2026-4-5 02:30:00", "twice")):
            with self.subTest(local), self.assertRaises(bp.clk.ClockError) as caught:
                bp.omh({**ROW, "date_excel": local})
            self.assertIn(word, str(caught.exception))
        # An hour either side exists once.
        self.assertEqual(bp.omh({**ROW, "date_excel": "2026-4-5 03:30:00"})["effective_time_frame"]["date_time"],
                         "2026-04-05T03:30:00+10:00")
        self.assertEqual(bp.omh({**ROW, "date_excel": "2026-10-4 01:30:00"})["effective_time_frame"]["date_time"],
                         "2026-10-04T01:30:00+10:00")

    def test_identity_and_the_export_s_own_fields_stay_as_written(self):
        p = bp.omh(ROW)
        for key in ("date_excel", "reading", "pulse", "location", "date"):
            self.assertEqual(p[key], ROW[key])

    def test_posture_maps_only_when_known_and_location_never(self):
        p = bp.omh(ROW)
        self.assertEqual(p["body_posture"], "sitting")
        self.assertNotIn("posture", p)
        unknown = bp.omh({**ROW, "posture": "Reclined"})
        self.assertNotIn("body_posture", unknown)
        self.assertEqual(unknown["posture"], "Reclined")  # v4 refuses it: a person names it
        self.assertNotIn("measurement_location", p)


if __name__ == "__main__":
    unittest.main()
