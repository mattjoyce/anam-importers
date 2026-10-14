"""The rebuild drill (anam card 141) against two real daemons: one stands for the
live record, seeded the way the gateway seeds it, and the drill builds the other from
the same folder. A clean drill matches it facet for facet; a fact the source no
longer holds shows as only-live."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin
from tests.test_records import FLIGHTS, LABS, PLUGIN, SUBMIT, TYPES, WEIGHTS, folder

DRILL = REPO / "scripts" / "rebuild-drill.py"


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN names no anam binary")
class RebuildDrill(unittest.TestCase):
    def drill(self, records_dir: str, live: Daemon, work: Path) -> dict:
        plan = work.parent / "plan.json"
        plan.write_text(json.dumps({"person_id": "person-a", "importers": [
            {"source": "records", "plugin": "records",
             "config": {"records_dir": records_dir, "person_id": "person-a"}}]}))
        token = work.parent / "live-token"
        token.write_text((Path(live.dir.name) / "token").read_text())
        out = subprocess.run([sys.executable, str(DRILL), "--anam", os.environ["ANAM_BIN"], "--plan", str(plan),
                              "--work", str(work), "--live-url", live.url, "--live-token-file", str(token)],
                             capture_output=True, text=True, timeout=300, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads((work / "report.json").read_text())

    def test_a_rebuild_matches_the_record_and_names_what_the_source_dropped(self):
        with folder({"a-labs.yaml": LABS, "b-weights.yml": WEIGHTS, "c-flights.json": FLIGHTS}) as d, \
                tempfile.TemporaryDirectory() as scratch:
            live = Daemon("records", TYPES)
            try:
                for ev in run_plugin(PLUGIN, {"command": "poll",
                                              "config": {"records_dir": d, "person_id": "person-a"}})["events"]:
                    r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                            "config": {"anam_url": live.url, "token_secret": "t"},
                                            "secrets": {"t": live.token}})
                    self.assertEqual(r["status"], "ok", r)

                report = self.drill(d, live, Path(scratch) / "one")
                self.assertEqual(report["importers"]["records"]["outcomes"], {"admitted": 6})
                for typ, c in report["compare"].items():
                    self.assertEqual((c["live"], c["only_live"], c["only_scratch"], c["differ"]),
                                     (c["scratch"], [], [], []), typ)

                # The source drops a weigh-in the record still holds.
                lines = WEIGHTS.splitlines(keepends=True)
                (Path(d) / "b-weights.yml").write_text("".join(l for l in lines if "w-2, date" not in l))
                report = self.drill(d, live, Path(scratch) / "two")
                self.assertEqual(len(report["compare"]["health.weight"]["only_live"]), 1)
            finally:
                live.close()


if __name__ == "__main__":
    unittest.main()
