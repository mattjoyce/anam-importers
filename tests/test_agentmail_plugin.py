"""The agentmail plugin (anam card 242), driven the way the gateway drives it: a request on
stdin, a response on stdout, against a real HTTP server on 127.0.0.1 that speaks the AgentMail
calls. Synthetic mail only: nothing here is a real invoice, address or message."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from tests.helpers import REPO

ENTRY = REPO / "agentmail" / "run.py"
KEY = "am_synthetic_key_0123456789"
MID = "<synthetic-1@mail.example.test>"
AUTH = {"spf": "pass", "dkim": "pass", "dmarc": "pass", "spf_domain": "example.test",
        "dkim_domain": "example.test", "dmarc_domain": "example.test"}


def make_pdf(text: str) -> bytes:
    """A one-page PDF whose text pdftotext can read."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
            b"/Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % off for off in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return out


PDF = make_pdf("Synthetic invoice 0042 Total 12.00")


class Fake:
    def __init__(self):
        self.files = {}      # attachment_id -> bytes served
        self.messages = []
        self.keys_at_download = []


def serve(fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            u = urlparse(self.path)
            if u.path.startswith("/dl/"):
                fake.keys_at_download.append(self.headers.get("Authorization"))
                return self._send(200, fake.files[u.path[4:]])
            if self.headers.get("Authorization") != f"Bearer {KEY}":
                return self._send(401, b"{}")
            parts = unquote(u.path).split("/")
            if parts[-1] == "messages":
                q = parse_qs(u.query)
                limit = int(q["limit"][0])
                start = int(q.get("page_token", ["0"])[0])
                page = fake.messages[start:start + limit]
                nxt = str(start + limit) if start + limit < len(fake.messages) else None
                return self._send(200, json.dumps({"count": len(page), "messages": page, "next_page_token": nxt}).encode())
            if "attachments" in parts:
                return self._send(200, json.dumps({"download_url": f"http://127.0.0.1:{self.server.server_port}/dl/{parts[-1]}"}).encode())
            return self._send(404, b"{}")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def att(aid, name, body, ctype="application/pdf", size=None):
    return {"attachment_id": aid, "filename": name, "size": len(body) if size is None else size, "content_type": ctype}


def message(mid, atts, auth=AUTH):
    m = {"message_id": mid, "timestamp": "2026-10-25T07:12:36.000Z", "from": "Someone <s@example.test>",
         "to": ["inbox@agentmail.test"], "subject": "Fwd: receipt", "attachments": atts}
    if auth is not None:
        m["authentication_results"] = auth
    return m


def key_of(mid):
    return hashlib.sha256(mid.encode()).hexdigest()[:16]


class PluginTest(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.srv = serve(self.fake)
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.spool = Path(self.tmp.name) / "spool"

    def add(self, mid, atts_with_bodies, auth=AUTH):
        atts = []
        for aid, name, body, *rest in atts_with_bodies:
            self.fake.files[aid] = body
            atts.append(att(aid, name, body, *rest))
        self.fake.messages.append(message(mid, atts, auth))

    def run_cmd(self, command, key=KEY, **config):
        cfg = {"agentmail_inbox": "inbox@agentmail.test", "mail_spool": str(self.spool),
               "base_url": f"http://127.0.0.1:{self.srv.server_port}", **config}
        req = {"command": command, "config": cfg, "secrets": {"AGENTMAIL_API_KEY": key} if key else {}}
        out = subprocess.run([sys.executable, str(ENTRY)], input=json.dumps(req), capture_output=True, text=True,
                             timeout=120)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn(KEY, out.stdout + out.stderr)
        return json.loads(out.stdout)

    def test_first_poll_spools_and_emits(self):
        self.add(MID, [("a1", "Invoice 0042.pdf", PDF)])
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "ok", r)
        folder = self.spool / key_of(MID)
        self.assertEqual((folder / "attachments" / "1-Invoice 0042.pdf").read_bytes(), PDF)
        self.assertIn("Synthetic invoice 0042", (folder / "attachments" / "1-Invoice 0042.pdf.txt").read_text())
        meta = json.loads((folder / "message.json").read_text())
        self.assertEqual(meta["message_id"], MID)
        self.assertEqual(meta["inbox"], "inbox@agentmail.test")
        self.assertEqual(meta["auth"], AUTH)
        self.assertEqual(meta["received_at"], "2026-10-25T07:12:36.000Z")
        self.assertEqual(meta["attachments"][0]["sha256"], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(meta["attachments"][0]["text"], "1-Invoice 0042.pdf.txt")
        self.assertEqual([e["type"] for e in r["events"]], ["agentmail.pdf"])
        self.assertEqual(r["events"][0]["payload"], {
            "payload_dir": str(folder.resolve()),
            "pdf": str(folder.resolve() / "attachments" / "1-Invoice 0042.pdf"),
            "input_file": str(folder.resolve() / "attachments" / "1-Invoice 0042.pdf.txt")})

    def test_second_poll_writes_nothing(self):
        self.add(MID, [("a1", "i.pdf", PDF)])
        self.run_cmd("poll")
        before = sorted((p, p.stat().st_mtime_ns) for p in self.spool.rglob("*"))
        downloads = len(self.fake.keys_at_download)
        r = self.run_cmd("poll")
        self.assertEqual(r["events"], [])
        self.assertEqual(sorted((p, p.stat().st_mtime_ns) for p in self.spool.rglob("*")), before)
        self.assertEqual(len(self.fake.keys_at_download), downloads)

    def test_a_non_pdf_is_spooled_without_an_event(self):
        self.add(MID, [("a1", "logo.png", b"\x89PNG synthetic", "image/png"), ("a2", "i.pdf", PDF)])
        r = self.run_cmd("poll")
        att_dir = self.spool / key_of(MID) / "attachments"
        self.assertEqual(sorted(p.name for p in att_dir.iterdir()), ["1-logo.png", "2-i.pdf", "2-i.pdf.txt"])
        self.assertEqual(len(r["events"]), 1)
        self.assertTrue(r["events"][0]["payload"]["pdf"].endswith("2-i.pdf"))

    def test_a_message_with_no_pdf_is_spooled_with_no_event(self):
        self.add(MID, [("a1", "notes.txt", b"hello", "text/plain")])
        self.add("<synthetic-2@mail.example.test>", [])
        r = self.run_cmd("poll")
        self.assertEqual(r["events"], [])
        self.assertTrue((self.spool / key_of(MID) / "message.json").is_file())
        self.assertTrue((self.spool / key_of("<synthetic-2@mail.example.test>") / "message.json").is_file())

    def test_a_failed_attachment_leaves_no_folder_and_is_retried(self):
        bad = "<synthetic-bad@mail.example.test>"
        self.add(bad, [("b1", "good.pdf", PDF), ("b2", "short.pdf", PDF, "application/pdf", len(PDF) + 5)])
        self.add(MID, [("a1", "i.pdf", PDF)])
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "ok", r)
        self.assertFalse((self.spool / key_of(bad)).exists())
        self.assertEqual([p.name for p in self.spool.iterdir()], [key_of(MID)])  # no temporary folder left
        self.assertEqual(len(r["events"]), 1)
        self.assertTrue(any("failed" in l["message"] and key_of(bad) in l["message"] for l in r["logs"]), r["logs"])
        # The inbox is fixed; the next poll spools the message whole.
        self.fake.messages[0]["attachments"][1]["size"] = len(PDF)
        r = self.run_cmd("poll")
        self.assertEqual(len(r["events"]), 2)
        self.assertTrue((self.spool / key_of(bad) / "message.json").is_file())

    def test_a_pdf_without_the_header_is_a_failure_not_a_crash(self):
        self.add(MID, [("a1", "i.pdf", b"<html>not a pdf</html>")])
        r = self.run_cmd("poll")
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"], [])
        self.assertEqual(list(self.spool.iterdir()), [])
        self.assertTrue(any("no %PDF header" in l["message"] for l in r["logs"]))

    def test_a_pdf_pdftotext_cannot_read_is_a_failure(self):
        self.add(MID, [("a1", "i.pdf", b"%PDF-1.4 garbage with no structure")])
        r = self.run_cmd("poll")
        self.assertEqual(r["events"], [])
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_a_stale_temporary_folder_is_cleared(self):
        stale = self.spool / ".tmp-dead-1"
        stale.mkdir(parents=True)
        (stale / "x").write_text("half")
        self.run_cmd("poll")
        self.assertFalse(stale.exists())

    def test_event_paths_sit_under_the_spool(self):
        self.add(MID, [("a1", "../../etc/evil.pdf", PDF)])
        r = self.run_cmd("poll")
        root = self.spool.resolve()
        for ev in r["events"]:
            for k in ("payload_dir", "pdf", "input_file"):
                p = Path(ev["payload"][k])
                self.assertTrue(p.is_absolute())
                root_ok = p == root or root in p.parents
                self.assertTrue(root_ok, p)
                self.assertTrue(p.exists(), p)

    def test_missing_auth_results_are_null(self):
        self.add(MID, [("a1", "i.pdf", PDF)], auth=None)
        self.run_cmd("poll")
        self.assertIsNone(json.loads((self.spool / key_of(MID) / "message.json").read_text())["auth"])

    def test_the_key_goes_to_the_api_only(self):
        self.add(MID, [("a1", "i.pdf", PDF)])
        r = self.run_cmd("poll")
        self.assertEqual(self.fake.keys_at_download, [None])
        self.assertNotIn(KEY, json.dumps(r))

    def test_a_wrong_key_is_an_error_without_the_key(self):
        r = self.run_cmd("poll", key="wrong-key-value")
        self.assertEqual(r["status"], "error")
        self.assertTrue(r["retry"])
        self.assertNotIn("wrong-key-value", json.dumps(r))

    def test_no_secret_is_an_error(self):
        r = self.run_cmd("poll", key="")
        self.assertEqual((r["status"], r["retry"]), ("error", False))

    def test_health(self):
        self.assertEqual(self.run_cmd("health")["status"], "ok")
        r = self.run_cmd("health", key="wrong-key-value")
        self.assertEqual(r["status"], "error")
        self.assertIn("does not read the inbox", r["error"])

    def test_pages_are_followed(self):
        for i in range(3):
            self.add(f"<synthetic-p{i}@mail.example.test>", [("p%d" % i, "i.pdf", PDF)])
        r = self.run_cmd("poll", page_size=2)
        self.assertEqual(len(r["events"]), 3)


if __name__ == "__main__":
    unittest.main()
