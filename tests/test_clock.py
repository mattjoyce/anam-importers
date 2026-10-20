"""anam_importer.clock: source_time, and a wall clock read in a zone without a guess
across a daylight-saving change (anam card 197)."""

import unittest
from datetime import datetime, timedelta, timezone

from anam_importer import clock


class LocalInstantTest(unittest.TestCase):
    def test_a_wall_clock_that_exists_once_is_its_instant(self):
        # Acceptance example 3's policy: a wall clock with no offset is read in a named zone.
        cases = [("2026-10-20 20:00", "Australia/Sydney", "2026-10-20T09:00:00Z"),
                 ("2026-10-20 20:00", "Europe/London", "2026-10-20T19:00:00Z"),
                 ("2026-04-05 03:30", "Australia/Sydney", "2026-04-04T17:30:00Z"),
                 ("2026-10-04 03:00", "Australia/Sydney", "2026-10-03T16:00:00Z")]
        for wall, zone, want in cases:
            with self.subTest(wall=wall, zone=zone):
                self.assertEqual(clock.utc_text(clock.local_instant(datetime.fromisoformat(wall), zone)), want)

    def test_a_wall_clock_the_zone_skips_or_repeats_is_refused(self):
        # Acceptance example 4: never a silent pick of a side.
        cases = [("2026-10-04 02:30", "Australia/Sydney", "does not exist"),
                 ("2026-04-05 02:30", "Australia/Sydney", "happens twice"),
                 ("2026-03-29 01:30", "Europe/London", "does not exist"),
                 ("2026-10-25 01:30", "Europe/London", "happens twice")]
        for wall, zone, want in cases:
            with self.subTest(wall=wall, zone=zone):
                with self.assertRaisesRegex(clock.ClockError, want):
                    clock.local_instant(datetime.fromisoformat(wall), zone)

    def test_a_time_that_already_has_an_offset_is_not_a_wall_clock(self):
        with self.assertRaises(ValueError):
            clock.local_instant(datetime(2026, 10, 20, 20, tzinfo=timezone.utc), "Australia/Sydney")


class SourceTimeTest(unittest.TestCase):
    def test_it_is_the_value_the_zone_and_the_basis(self):
        self.assertEqual(clock.source_time("2026-10-20T20:00:00+11:00", "+11:00", "source"),
                         {"value": "2026-10-20T20:00:00+11:00", "zone": "+11:00", "basis": "source"})

    def test_a_basis_or_a_zone_the_gate_would_refuse_is_refused_before_it_is_sent(self):
        for zone in ("Europe/London", "UTC", "+01:00", "-03:30", "+14:00"):
            with self.subTest(zone=zone):
                clock.source_time("x", zone, "configuration")
        for zone in ("Europe/Londn", "Local", "", "+15:00", "+1:00", "../etc/passwd"):
            with self.subTest(zone=zone):
                with self.assertRaises(ValueError):
                    clock.source_time("x", zone, "configuration")
        with self.assertRaises(ValueError):
            clock.source_time("x", "UTC", "guessed")

    def test_an_offset_is_written_as_rfc_3339_writes_one(self):
        t = datetime(2026, 10, 17, 13, tzinfo=timezone.utc)
        self.assertEqual(clock.at_offset(t, timedelta(hours=11)), "2026-10-18T00:00:00+11:00")
        self.assertEqual(clock.at_offset(t, timedelta(hours=-3, minutes=-30)), "2026-10-17T09:30:00-03:30")
        self.assertEqual(clock.at_offset(t, timedelta(0)), "2026-10-17T13:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
