"""records/extract/add_source_time.py: the source_time block added to the records of the six
types that require it (anam card 198), and the check that a staging folder changed nothing
else."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.helpers import REPO

_spec = importlib.util.spec_from_file_location("add_source_time", REPO / "records" / "extract" / "add_source_time.py")
add = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(add)

FILE = """\
document:
  name: report.pdf
  sha256: abc
extracted:
  method: hand
  version: 1
records:
- type: health.weight
  id: w1
  date: 2026-01-24 06:33
  kg: 80.1
- type: health.weight
  id: w2
  date: 2026-06-24 06:33
  kg: 79.0
- type: health.lab-result
  id: acl:1/sodium
  collected: 2026-01-30 08:53
  analyte: Sodium
  value: '137'
  lab_number: '1'
- type: health.lab-result
  id: acl:2/sodium
  collected: 2026-10-12 07:30
  source_time:
    value: 2026-10-12 07:30
    zone: Australia/Sydney
    basis: assumption
  analyte: Sodium
  value: '137'
  lab_number: '2'
- type: health.encounter
  id: gp:1
  date: 2014-02-27 00:00
  time_unknown: 'True'
  provider: A GP
- type: health.blood-pressure
  id: bp:1
  date_excel: '2024-9-16 06:14:00'
  reading: '1'
- type: place.trip.departed
  id: trip:1
  date: '2026-10-17'
"""


class AddSourceTimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.live = Path(self.tmp.name) / "records"
        self.live.mkdir()
        self.out = Path(self.tmp.name) / "staging"

    def run_script(self, *extra) -> int:
        return add.main([*extra, str(self.live)])

    def stage(self, text: str = FILE) -> dict:
        (self.live / "a.yaml").write_text(text)
        self.assertEqual(self.run_script("--out", str(self.out)), 0)
        return {r["id"]: r for r in yaml.safe_load((self.out / "a.yaml").read_text())["records"]}

    def test_every_target_record_gets_the_block_and_nothing_else_moves(self):
        recs = self.stage()
        self.assertEqual(recs["w1"]["source_time"], {"value": "2026-01-24 06:33", "zone": "Australia/Sydney", "offset": "+11:00", "basis": "source"})
        # Weight alone carries the offset, and it is the date's own: Sydney is +10:00 in June.
        self.assertEqual(recs["w2"]["source_time"]["offset"], "+10:00")
        self.assertEqual(recs["acl:1/sodium"]["source_time"], {"value": "2026-01-30 08:53", "zone": "Australia/Sydney", "basis": "source"})
        self.assertEqual(recs["bp:1"]["source_time"]["value"], "2024-9-16 06:14:00")
        # A draw with no time known is given its date alone, as the report printed it.
        self.assertEqual(recs["gp:1"]["source_time"]["value"], "2014-02-27")
        self.assertNotIn("source_time", recs["trip:1"])
        # An existing block in Sydney that said assumption now says source, its other lines alone.
        self.assertEqual(recs["acl:2/sodium"]["source_time"]["basis"], "source")
        old, new = FILE.split("\n"), (self.out / "a.yaml").read_text().split("\n")
        self.assertEqual(add.line_diff_is_blocks_only(old, new), [])
        self.assertEqual(add.verify(self.live, self.out), [])

    def test_a_wall_clock_sydney_skips_or_repeats_stops_the_run_and_writes_nothing_for_that_file(self):
        for at, word in (("2026-10-04 02:30", "skip"), ("2026-04-05 02:30", "twice")):
            with self.subTest(at):
                (self.live / "a.yaml").write_text(FILE.replace("2026-01-24 06:33", at))
                self.assertEqual(self.run_script("--out", str(self.out)), 1)
                self.assertFalse((self.out / "a.yaml").exists())

    def test_the_records_folder_is_never_the_output(self):
        (self.live / "a.yaml").write_text(FILE)
        with self.assertRaises(SystemExit):
            self.run_script("--out", str(self.live))

    def test_a_dry_run_writes_nothing(self):
        (self.live / "a.yaml").write_text(FILE)
        self.assertEqual(self.run_script(), 0)
        self.assertEqual((self.live / "a.yaml").read_text(), FILE)

    def test_an_existing_block_in_another_zone_stops_it(self):
        (self.live / "a.yaml").write_text(FILE.replace("zone: Australia/Sydney\n    basis: assumption", "zone: Europe/London\n    basis: assumption"))
        self.assertEqual(self.run_script("--out", str(self.out)), 1)

    def test_verify_finds_a_staged_file_that_changed_something_else(self):
        self.stage()
        staged = self.out / "a.yaml"
        text = staged.read_text().replace("kg: 80.1", "kg: 80.2")
        staged.write_text(text)
        self.assertTrue(any("changed since it was written" in p or "is not an added block" in p for p in add.verify(self.live, self.out)))

    def test_verify_finds_an_original_that_changed_after_staging(self):
        self.stage()
        (self.live / "a.yaml").write_text(FILE.replace("kg: 80.1", "kg: 81.0"))
        self.assertTrue(any("original has changed" in p for p in add.verify(self.live, self.out)))


if __name__ == "__main__":
    unittest.main()
