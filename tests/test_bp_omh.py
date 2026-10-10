"""The blood pressure reading as an Open mHealth body (anam card 83)."""

import importlib.util
import unittest

from tests.helpers import REPO

_spec = importlib.util.spec_from_file_location("bp_csv_run", REPO / "bp_csv" / "run.py")
bp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bp)

ROW = {"date_excel": "2026-1-24 06:36:00", "date": "24 January 2026 6:36", "systolic": "114.0",
       "diastolic": "80", "pulse": "70.0", "location": "Left Arm", "posture": "Seated", "reading": "1"}


class OMHTest(unittest.TestCase):
    def test_pressures_are_numbers_in_mmhg_and_nothing_is_rounded(self):
        p = bp.omh(ROW)
        self.assertEqual(p["systolic_blood_pressure"], {"value": 114.0, "unit": "mmHg"})
        self.assertEqual(p["diastolic_blood_pressure"], {"value": 80, "unit": "mmHg"})
        self.assertNotIn("systolic", p)

    def test_the_time_carries_sydney_s_offset_for_its_date(self):
        cases = [("2026-1-24 06:36:00", "2026-01-24T06:36:00+11:00"), ("2025-5-29 05:41:00", "2025-05-29T05:41:00+10:00")]
        for local, want in cases:
            with self.subTest(local):
                self.assertEqual(bp.omh({**ROW, "date_excel": local})["effective_time_frame"]["date_time"], want)

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
