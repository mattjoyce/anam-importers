"""anam_links (anam card 165): a folder of files shaped as record.link, a file Anam
remembers but does not hold. Invented files under a temporary folder, and a real
daemon with ANAM_BIN.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import struct
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests.helpers import REPO, Daemon, run_plugin

PLUGIN = REPO / "links" / "run.py"
SUBMIT = REPO / "anam_submit" / "run.py"

NOTE = "---\ndate: 2024-03-02\ntitle: A synthetic note\nid: note-0001\n---\n# Nothing real\n"
PHOTO = b"\x89PNG synthetic, not a photo"
SHA = lambda b: hashlib.sha256(b if isinstance(b, bytes) else b.encode()).hexdigest()  # noqa: E731


def jpeg_with_exif(taken: str, offset: str = "") -> bytes:
    """The least JPEG that carries EXIF DateTimeOriginal (and OffsetTimeOriginal when
    offset is given): SOI, one APP1 segment, EOI. Little-endian TIFF, IFD0 pointing at
    an Exif IFD, the strings after the IFDs."""
    tags = [(0x9003, taken.encode() + b"\x00")]
    if offset:
        tags.append((0x9011, offset.encode() + b"\x00"))
    ifd0_at, exif_at = 8, 8 + 2 + 12 + 4
    strings_at = exif_at + 2 + 12 * len(tags) + 4
    tiff = b"II*\x00" + struct.pack("<I", ifd0_at)
    tiff += struct.pack("<H", 1) + struct.pack("<HHII", 0x8769, 4, 1, exif_at) + struct.pack("<I", 0)
    entries, blob = b"", b""
    for tag, text in tags:
        entries += struct.pack("<HHII", tag, 2, len(text), strings_at + len(blob))
        blob += text
    tiff += struct.pack("<H", len(tags)) + entries + struct.pack("<I", 0) + blob
    app1 = b"Exif\x00\x00" + tiff
    return b"\xff\xd8" + b"\xff\xe1" + struct.pack(">H", len(app1) + 2) + app1 + b"\xff\xd9"


@contextlib.contextmanager
def folder(files):
    """A folder holding files, a dict of relative path to bytes or text. The state
    file the tests pass sits beside it (state_of), never in it."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d) / "files"
        root.mkdir()
        for rel, body in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            (p.write_bytes if isinstance(body, bytes) else p.write_text)(body)
        yield root


def state_of(d):
    return d.parent / "state.json"


def config(d, **more):
    base = {"links_dir": str(d), "root_name": "vault", "person_id": "person-a", "identity": "path",
            "zone": "Australia/Sydney", "state_file": str(state_of(d))}
    base.update(more)
    return base


def run(command, d, **more):
    return run_plugin(PLUGIN, {"command": command, "config": config(d, **more)})


def payloads(out):
    envs = [e for ev in out["events"] for e in ev["payload"]["envelopes"]]
    return {e["payload"]["id"]: e["payload"] for e in envs}


class ShapeTest(unittest.TestCase):
    def test_each_file_is_one_link_keyed_by_the_instance_mode(self):
        files = {"notes/2024-03-02 note.md": NOTE, "photos/2024-04-05 scan.png": PHOTO, ".obsidian/x.md": NOTE}
        with folder(files) as d:
            # One state file per mode: one folder under two modes is two instances.
            by_mode = {mode: run("poll", d, identity=mode, state_file=str(d.parent / f"{mode}.json")) for mode in ("path", "content")}
        for mode, out in by_mode.items():
            self.assertEqual(out["status"], "ok", out)
        got = payloads(by_mode["path"])
        self.assertEqual(sorted(got), ["path:vault/notes/2024-03-02 note.md", "path:vault/photos/2024-04-05 scan.png"])
        note = got["path:vault/notes/2024-03-02 note.md"]
        self.assertEqual(note, {"id": "path:vault/notes/2024-03-02 note.md", "identity": "path", "root": "vault",
                                "path": "notes/2024-03-02 note.md", "sha256": SHA(NOTE), "bytes": len(NOTE.encode()),
                                "media_type": "text/markdown", "date": "2024-03-02T00:00:00+11:00",
                                "date_from": "frontmatter", "title": "A synthetic note"})
        photo = got["path:vault/photos/2024-04-05 scan.png"]
        self.assertEqual((photo["date"], photo["date_from"], photo["media_type"]),
                         ("2024-04-05T00:00:00+11:00", "filename", "image/png"))
        self.assertNotIn("title", photo)
        self.assertEqual(sorted(payloads(by_mode["content"])), sorted(["content:" + SHA(NOTE), "content:" + SHA(PHOTO)]))
        ev = by_mode["path"]["events"][0]
        self.assertEqual(ev["type"], "anam_links.batch")
        self.assertEqual(ev["payload"]["snapshot"]["types"], ["record.link"])
        self.assertIn('"facet_type": "record.link"', ev["payload"]["definitions"][0])
        self.assertNotIn("documents", ev["payload"])  # no bytes are handed to anyone
        for env in ev["payload"]["envelopes"]:
            self.assertEqual((env["type"], env["asserted_person"]), ("record.link", "person-a"))

    def test_id_mode_keys_on_the_declared_id_and_skips_a_file_without_one(self):
        files = {"a/first.md": NOTE, "b/moved and edited.md": NOTE.replace("Nothing real", "Edited"),
                 "no-id.md": "---\ndate: 2024-01-01\n---\n", "photo.png": PHOTO}
        with folder(files) as d:
            out = run("poll", d, identity="id")
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual(sorted(payloads(out)), ["id:note-0001"])
        self.assertEqual(payloads(out)["id:note-0001"]["path"], "a/first.md")
        logs = [l["message"] for l in out["logs"]]
        self.assertTrue(any(l.startswith("skipped no-id.md: no id") for l in logs), logs)
        self.assertTrue(any(l.startswith("skipped photo.png: no id") for l in logs), logs)
        self.assertTrue(any(l.startswith("skipped b/moved and edited.md: its id id:note-0001 is also a/first.md's") for l in logs), logs)
        self.assertIn("1 file(s) seen, 0 unseen, 3 skipped", out["result"])

    def test_fact_time_is_the_first_source_that_answers(self):
        cases = {
            "frontmatter bare date": ("n.md", "---\ndate: 2024-03-02\n---\n", "2024-03-02T00:00:00+11:00", "frontmatter"),
            "frontmatter time no zone": ("n.md", "---\ndate: 2024-07-02 09:15\n---\n", "2024-07-02T09:15:00+10:00", "frontmatter"),
            "frontmatter with offset": ("n.md", "---\ndate: 2024-07-02T09:15:00+02:00\n---\n", "2024-07-02T09:15:00+02:00", "frontmatter"),
            "frontmatter Z": ("n.md", "---\ndate: 2024-07-02T09:15:00Z\n---\n", "2024-07-02T09:15:00+00:00", "frontmatter"),
            "frontmatter beats the file name": ("2020-01-01 n.md", "---\ndate: 2024-03-02\n---\n", "2024-03-02T00:00:00+11:00", "frontmatter"),
            "exif in the zone": ("p.jpg", jpeg_with_exif("2024:07:02 09:15:30"), "2024-07-02T09:15:30+10:00", "exif"),
            "exif with its own offset": ("p.jpg", jpeg_with_exif("2024:07:02 09:15:30", "+02:00"), "2024-07-02T09:15:30+02:00", "exif"),
            "exif beats the file name": ("2020-01-01 p.jpg", jpeg_with_exif("2024:07:02 09:15:30"), "2024-07-02T09:15:30+10:00", "exif"),
            "a bad exif date falls through": ("2020-01-01 p.jpg", jpeg_with_exif("not a date"), "2020-01-01T00:00:00+11:00", "filename"),
            "no exif, file name": ("2024-04-05 p.jpg", b"\xff\xd8\xff\xd9", "2024-04-05T00:00:00+11:00", "filename"),
            "file name prefix": ("2024-04-05_scan.png", PHOTO, "2024-04-05T00:00:00+11:00", "filename"),
            "a longer number is not a date": ("2024-04-051.png", PHOTO, None, "mtime"),
        }
        for name, (file, body, date, source) in cases.items():
            with self.subTest(name), folder({file: body}) as d:
                os.utime(d / file, (1_700_000_000, 1_700_000_000))
                out = run("poll", d, identity="content")
                self.assertEqual(out["status"], "ok", out)
                (got,) = payloads(out).values()
                self.assertEqual(got["date_from"], source)
                self.assertEqual(got["date"], date or "2023-11-15T09:13:20+11:00")

    def test_mtime_is_refused_for_markdown_and_a_bad_frontmatter_date_is_reported(self):
        files = {"undated.md": "# no frontmatter\n", "bad.md": "---\ndate: March 2nd\n---\n",
                 "list.md": "---\ndate: [1]\n---\n", "open.md": "---\ndate: 2024-01-01\n# never closed\n",
                 "2024-01-01 named.md": "# dated by name\n"}
        with folder(files) as d:
            out = run("poll", d)
        self.assertEqual(out["status"], "ok", out)
        self.assertEqual(sorted(payloads(out)), ["path:vault/2024-01-01 named.md"])
        logs = {l["message"].split(":")[0]: l["message"] for l in out["logs"]}
        self.assertIn("mtime is refused for Markdown", logs["skipped undated.md"])
        self.assertIn("not YYYY-MM-DD", logs["skipped bad.md"])
        self.assertIn("not text", logs["skipped list.md"])
        self.assertIn("never closes", logs["skipped open.md"])
        # open.md went unread, so this run claims no snapshot; the others were read and
        # excluded by the instance's rules, which alone would not withhold it.
        self.assertNotIn("snapshot", out["events"][0]["payload"])
        self.assertIn("no snapshot: 1 file(s) could not be read", out["result"])
        with folder({k: v for k, v in files.items() if k != "open.md"}) as d:
            out = run("poll", d)
        self.assertIn("snapshot", out["events"][0]["payload"])
        self.assertEqual(len(out["logs"]), 3)

    def test_a_tiff_carries_exif_too_and_other_kinds_are_not_read(self):
        tiff = jpeg_with_exif("2024:07:02 09:15:30")[4 + 2 + 6:-2]  # the TIFF block alone
        with folder({"2020-01-01 a.tif": tiff, "2020-01-01 b.png": tiff}) as d:
            out = run("poll", d)
        got = payloads(out)
        self.assertEqual(got["path:vault/2020-01-01 a.tif"]["date_from"], "exif")
        self.assertEqual(got["path:vault/2020-01-01 b.png"]["date_from"], "filename")

    def test_a_file_unseen_past_the_tolerance_is_superseded_not_retracted_and_comes_back(self):
        with folder({"a.png": PHOTO, "2024-01-01 b.png": PHOTO + b" b"}) as d:
            first = run("poll", d, unseen_after=2)
            self.assertEqual(sorted(payloads(first)), ["path:vault/2024-01-01 b.png", "path:vault/a.png"])
            state = json.loads(state_of(d).read_text())
            self.assertEqual(sorted(state["known"]), sorted(payloads(first)))
            b_was = payloads(first)["path:vault/2024-01-01 b.png"]

            (d / "2024-01-01 b.png").unlink()
            second = run("poll", d, unseen_after=2)
            self.assertEqual(payloads(second)["path:vault/2024-01-01 b.png"], b_was)  # as it was, one miss
            self.assertIn("1 file(s) seen, 0 unseen", second["result"])

            third = run("poll", d, unseen_after=2)
            gone = payloads(third)["path:vault/2024-01-01 b.png"]
            self.assertTrue(gone.pop("unseen"))
            since, last = gone.pop("unseen_since"), gone.pop("last_seen")
            self.assertEqual(gone, b_was)
            self.assertLessEqual(last, since)
            for stamp in (since, last):
                datetime.fromisoformat(stamp)
            self.assertIn("1 file(s) seen, 1 unseen", third["result"])
            self.assertEqual(third["events"][0]["payload"]["snapshot"]["types"], ["record.link"])

            fourth = run("poll", d, unseen_after=2)
            self.assertEqual(payloads(fourth)["path:vault/2024-01-01 b.png"]["unseen_since"], since)  # stable: a no-op

            (d / "2024-01-01 b.png").write_bytes(PHOTO + b" b")
            fifth = run("poll", d, unseen_after=2)
            self.assertEqual(payloads(fifth)["path:vault/2024-01-01 b.png"], b_was)
            self.assertEqual(json.loads(state_of(d).read_text())["known"]["path:vault/2024-01-01 b.png"]["misses"], 0)

    def test_an_unreachable_folder_is_no_run_and_health_writes_nothing(self):
        with folder({}) as d:
            out = run("poll", d / "not-mounted")
            self.assertEqual(out["status"], "error", out)
            self.assertTrue(out["retry"])
            self.assertIn("no run", out["error"])
            self.assertFalse(state_of(d).exists())
            (d / "a.png").write_bytes(PHOTO)
            health = run("health", d)
            self.assertEqual(health["status"], "ok", health)
            self.assertIn("1 file(s) under", health["result"])
            self.assertIn("1 on mtime (weak)", health["result"])
            self.assertFalse(state_of(d).exists())
            self.assertEqual(run("poll", d)["status"], "ok")
            self.assertTrue(state_of(d).exists())
            self.assertEqual(list(d.iterdir()), [d / "a.png"])  # the folder is read, never written

    def test_config_is_checked_at_start(self):
        cases = {
            "identity": {"identity": "name"},
            "zone": {"zone": "Mars/Olympus"},
            "root_name": {"root_name": "a/b"},
            "unseen_after": {"unseen_after": 0},
            "state_file": {"state_file": "{d}/.anam-links.json"},  # under links_dir: the source is never written
        }
        with folder({"a.png": PHOTO}) as d:
            for key, bad in cases.items():
                with self.subTest(key):
                    bad = {k: v.format(d=d) if isinstance(v, str) else v for k, v in bad.items()}
                    out = run("poll", d, **bad)
                    self.assertEqual(out["status"], "error", out)
                    self.assertIn(f"config {key}", out["error"])
                    self.assertFalse(out["retry"])
            self.assertFalse(state_of(d).exists())
            self.assertEqual(run_plugin(PLUGIN, {"command": "poll", "config": {k: v for k, v in config(d).items() if k != "state_file"}})["error"],
                             "config state_file: '' is not text")


@unittest.skipUnless(os.environ.get("ANAM_BIN"), "ANAM_BIN is not set")
class AgainstAnamTest(unittest.TestCase):
    def fresh(self):
        """A daemon of its own for each folder: a snapshot claims everything the
        instance stands behind, so facets from another instance would be absent."""
        self.daemon = Daemon("links", ["record.link"])
        self.addCleanup(self.daemon.close)

    def submit(self, out):
        outcomes, absent = {}, None
        self.assertEqual(out["status"], "ok", out)
        for ev in out["events"]:
            r = run_plugin(SUBMIT, {"command": "handle", "event": ev,
                                    "config": {"anam_url": self.daemon.url, "token_secret": "anam_importer_token_test"},
                                    "secrets": {"anam_importer_token_test": self.daemon.token}})
            self.assertEqual(r["status"], "ok", r)
            for o, n in r["events"][0]["payload"]["outcomes"].items():
                outcomes[o] = outcomes.get(o, 0) + n
            if "snapshot complete" in r["result"]:
                absent = r["result"]
            self.assertFalse([e for e in r["events"] if e["type"] == "anam.snapshot_absent"], r)
        self.assertIn("0 of", absent or "")  # the snapshot claimed everything: nothing is absent
        return outcomes

    def test_a_link_whose_bytes_nothing_holds_is_admitted_and_each_mode_supersedes_as_its_row_says(self):
        with folder({"notes/2024-03-02 note.md": NOTE, "2024-04-05 scan.png": PHOTO}) as d:
            self.fresh()
            # Admitted, with sha256s the library holds no bytes for: the held-bytes
            # refusal is keyed on doc.reference, not on this type.
            self.assertEqual(self.submit(run("poll", d)), {"admitted": 2})
            self.assertEqual(self.submit(run("poll", d)), {"no-op": 2})
            # path: new bytes supersede; a move is a new facet (and the old one is a
            # miss, carried as it was).
            (d / "2024-04-05 scan.png").write_bytes(PHOTO + b" again")
            self.assertEqual(self.submit(run("poll", d)), {"no-op": 1, "superseded": 1})
            (d / "2024-04-05 scan.png").rename(d / "2024-04-05 moved.png")
            self.assertEqual(self.submit(run("poll", d)), {"no-op": 2, "admitted": 1})
        with folder({"2024-04-05 scan.png": PHOTO, "notes/2024-03-02 note.md": NOTE}) as d:
            self.fresh()
            # content: a move supersedes with the new path; new bytes are a new facet.
            self.assertEqual(self.submit(run("poll", d, identity="content")), {"admitted": 2})
            (d / "2024-04-05 scan.png").rename(d / "2024-04-05 renamed.png")
            self.assertEqual(self.submit(run("poll", d, identity="content")), {"no-op": 1, "superseded": 1})
            (d / "2024-04-05 renamed.png").write_bytes(PHOTO + b" edited")
            self.assertEqual(self.submit(run("poll", d, identity="content")), {"no-op": 2, "admitted": 1})
        with folder({"notes/2024-03-02 note.md": NOTE}) as d:
            self.fresh()
            # id: a renamed and edited note supersedes rather than duplicates.
            self.assertEqual(self.submit(run("poll", d, identity="id")), {"admitted": 1})
            (d / "notes" / "2024-03-02 note.md").unlink()
            (d / "renamed.md").write_text(NOTE.replace("Nothing real", "Edited"))
            self.assertEqual(self.submit(run("poll", d, identity="id")), {"superseded": 1})
            self.assertEqual(self.submit(run("poll", d, identity="id")), {"no-op": 1})

    def test_unseen_is_a_supersession_and_a_returning_file_supersedes_back(self):
        with folder({"a.png": PHOTO, "2024-01-01 b.png": PHOTO + b" b"}) as d:
            self.fresh()
            self.assertEqual(self.submit(run("poll", d, unseen_after=2)), {"admitted": 2})
            (d / "2024-01-01 b.png").unlink()
            self.assertEqual(self.submit(run("poll", d, unseen_after=2)), {"no-op": 2})  # one miss: as it was
            self.assertEqual(self.submit(run("poll", d, unseen_after=2)), {"no-op": 1, "superseded": 1})  # unseen
            self.assertEqual(self.submit(run("poll", d, unseen_after=2)), {"no-op": 2})
            (d / "2024-01-01 b.png").write_bytes(PHOTO + b" b")
            self.assertEqual(self.submit(run("poll", d, unseen_after=2)), {"no-op": 1, "superseded": 1})  # back
            # Nothing was retracted: every facet is live, and the snapshot reports none absent (submit checks).


if __name__ == "__main__":
    unittest.main()
