"""anam_documents (anam card 103): a folder of documents with sidecars, shaped as Anam's
built-in documents worker shaped it, and handed to Anam's library through anam_submit.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

PLUGIN = REPO / "documents" / "run.py"
SUBMIT = REPO / "anam_submit" / "run.py"

LETTER = b"%PDF-1.4 a synthetic letter, not a real one"
NOTE = b"# A synthetic note\n\nNothing real.\n"


@contextlib.contextmanager
def library(files):
    """A folder holding files, a dict of relative path to bytes or text."""
    with tempfile.TemporaryDirectory() as d:
        for rel, body in files.items():
            p = Path(d) / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            (p.write_bytes if isinstance(body, bytes) else p.write_text)(body)
        yield Path(d)


def run(command, d):
    return run_plugin(PLUGIN, {"command": command, "config": {"documents_dir": str(d), "person_id": "person-a"}})


GOOD = {
    "scans/2024-03-01_letter.pdf": LETTER,
    "scans/2024-03-01_letter.pdf.meta.yaml": "date: 2024-03-01\ntitle: A letter\nnote: synthetic\n",
    "2024-04-02_note.md": NOTE,
    "2024-04-02_note.md.meta.yaml": "date: 2024-04-02\ntitle: '0777'\n",
    ".hidden.pdf": LETTER,
    ".git/x.pdf": LETTER,
}


class ShapeTest(unittest.TestCase):
    def test_each_document_is_one_reference_with_what_the_worker_measured(self):
        with library(GOOD) as d:
            out = run("poll", d)
        self.assertEqual(out["status"], "ok", out)
        ev = out["events"][0]["payload"]
        envs = {e["payload"]["path"]: e for e in ev["envelopes"]}
        self.assertEqual(sorted(envs), ["2024-04-02_note.md", "scans/2024-03-01_letter.pdf"])
        letter = envs["scans/2024-03-01_letter.pdf"]["payload"]
        self.assertEqual(letter, {"date": "2024-03-01", "title": "A letter", "note": "synthetic",
                                  "path": "scans/2024-03-01_letter.pdf", "sha256": hashlib.sha256(LETTER).hexdigest(),
                                  "bytes": len(LETTER), "media_type": "application/pdf"})
        note = envs["2024-04-02_note.md"]["payload"]
        self.assertEqual((note["title"], note["media_type"]), ("0777", "text/markdown"))  # quoted text stays text
        self.assertEqual({doc["path"] for doc in ev["documents"]}, set(envs))
        for doc in ev["documents"]:
            self.assertTrue(os.path.isabs(doc["file"]) and doc["file"].endswith(doc["path"]))
        self.assertTrue(ev["current_versions"])
        self.assertEqual(ev["snapshot"]["types"], ["doc.reference"])

    def test_a_file_without_a_usable_sidecar_refuses_the_run(self):
        cases = {
            "no sidecar": ({"a.pdf": LETTER}, "write"),
            "no date": ({"a.pdf": LETTER, "a.pdf.meta.yaml": "title: x\n"}, "date"),
            "a measured field declared": ({"a.pdf": LETTER, "a.pdf.meta.yaml": "date: 2024-01-01\nsha256: abc\n"}, "measured"),
            "not a mapping": ({"a.pdf": LETTER, "a.pdf.meta.yaml": "- 1\n"}, "mapping"),
        }
        for name, (files, says) in cases.items():
            with self.subTest(name), library(files) as d:
                out = run("poll", d)
                self.assertEqual(out["status"], "error", out)
                self.assertIn(says, out["error"])
                self.assertFalse(out.get("retry"), out)


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN is not set")
class AgainstAnamTest(unittest.TestCase):
    def submit(self, daemon, events):
        outcomes = {}
        for ev in events:
            r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                    "config": {"anam_url": daemon.url, "token_secret": "anam_importer_token_test"},
                                    "secrets": {"anam_importer_token_test": daemon.token}})
            self.assertEqual(r["status"], "ok", r)
            for o, n in r["events"][0]["payload"]["outcomes"].items():
                outcomes[o] = outcomes.get(o, 0) + n
        return outcomes

    def test_every_document_the_worker_admitted_resends_as_no_op_and_lands_in_the_library(self):
        with library(GOOD) as d:
            daemon = Daemon("documents", ["doc.reference"], imports=[("documents", d)])
            try:
                shaped = run("poll", d)
                self.assertEqual(self.submit(daemon, shaped["events"]), {"no-op": 2})
                held = Path(daemon.dir.name) / "documents" / (hashlib.sha256(LETTER).hexdigest() + ".pdf")
                self.assertEqual(held.read_bytes(), LETTER)  # named by its sha256 (anam card 150)
                self.assertFalse(list((Path(daemon.dir.name) / "documents").rglob("*.meta.yaml")))
                # A second run hands the same bytes again: unchanged, and no-op.
                self.assertEqual(self.submit(daemon, run("poll", d)["events"]), {"no-op": 2})
                # A new document is admitted with its bytes.
                (d / "2024-05-05_scan.png").write_bytes(b"\x89PNG synthetic")
                (d / "2024-05-05_scan.png.meta.yaml").write_text("date: 2024-05-05\n")
                self.assertEqual(self.submit(daemon, run("poll", d)["events"]), {"no-op": 2, "admitted": 1})
                # A rescan under the same name supersedes, and the first scan's bytes stay.
                rescan = LETTER + b", scanned again"
                (d / "scans" / "2024-03-01_letter.pdf").write_bytes(rescan)
                self.assertEqual(self.submit(daemon, run("poll", d)["events"]), {"no-op": 2, "superseded": 1})
                self.assertEqual(held.read_bytes(), LETTER)
                again = Path(daemon.dir.name) / "documents" / (hashlib.sha256(rescan).hexdigest() + ".pdf")
                self.assertEqual(again.read_bytes(), rescan)
            finally:
                daemon.close()


if __name__ == "__main__":
    unittest.main()
