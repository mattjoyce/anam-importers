"""anam_agentmail fetch (anam card 242), against a real HTTP server on 127.0.0.1 that
speaks the AgentMail calls the fetch makes. No mock of the fetch's own code."""

from __future__ import annotations

import csv
import hashlib
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse, parse_qs

from agentmail import fetch

PDF = b"%PDF-1.4 a synthetic invoice, not a real one"
PDF2 = b"%PDF-1.4 a second synthetic invoice"
KEY = "test-key"


class Fake:
    """The inbox's contents and the calls it has seen."""

    def __init__(self):
        self.files = {}      # attachment_id -> (bytes served, size the inbox reports)
        self.messages = []
        self.downloads = 0
        self.auth_on_download = []


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
                fake.downloads += 1
                fake.auth_on_download.append(self.headers.get("Authorization"))
                return self._send(200, fake.files[u.path[4:]][0], "application/pdf")
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
                aid = parts[-1]
                return self._send(200, json.dumps({"download_url": f"http://127.0.0.1:{self.server.server_port}/dl/{aid}"}).encode())
            return self._send(404, b"{}")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def message(mid, atts):
    return {"message_id": mid, "timestamp": "2026-10-25T07:12:36.000Z", "from": "Matt <m@example.test>",
            "subject": "Fwd: receipt", "attachments": atts}


def att(aid, name, size, ctype="application/pdf"):
    return {"attachment_id": aid, "filename": name, "size": size, "content_type": ctype}


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.fake = Fake()
        self.srv = serve(self.fake)
        self.addCleanup(self.srv.shutdown)
        self.addCleanup(self.srv.server_close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.spool = Path(self.tmp.name) / "spool"
        self.inbox = fetch.Inbox(f"http://127.0.0.1:{self.srv.server_port}", "box@agentmail.test", KEY, 5.0)

    def manifest(self):
        with (self.spool / fetch.MANIFEST).open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    def test_saves_attachments_byte_exact_and_writes_the_manifest(self):
        self.fake.files = {"a1": (PDF, len(PDF)), "a2": (PDF2, len(PDF2))}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "Invoice-X-0001.pdf", len(PDF)),
                                                         att("a2", "Receipt-1111.pdf", len(PDF2))])]
        rows = fetch.run(self.inbox, self.spool, 50)
        self.assertEqual([r["status"] for r in rows], ["ok", "ok"])
        saved = self.spool / fetch.stem("<m1@mail.test>") / "Invoice-X-0001.pdf"
        self.assertEqual(saved.read_bytes(), PDF)
        m = self.manifest()
        self.assertEqual(m[0]["sha256"], hashlib.sha256(PDF).hexdigest())
        self.assertEqual(m[1]["bytes"], str(len(PDF2)))

    def test_pages_through_the_whole_inbox(self):
        self.fake.files = {f"a{i}": (PDF, len(PDF)) for i in range(5)}
        self.fake.messages = [message(f"<m{i}@mail.test>", [att(f"a{i}", f"Invoice-{i}.pdf", len(PDF))]) for i in range(5)]
        self.assertEqual(len(fetch.run(self.inbox, self.spool, 2)), 5)

    def test_a_rerun_downloads_nothing_again(self):
        self.fake.files = {"a1": (PDF, len(PDF))}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "Invoice-X-0001.pdf", len(PDF))])]
        fetch.run(self.inbox, self.spool, 50)
        again = fetch.run(self.inbox, self.spool, 50)
        self.assertEqual(self.fake.downloads, 1)
        self.assertEqual(again[0]["detail"], "kept")
        self.assertEqual(again[0]["status"], "ok")

    def test_wrong_size_is_failed_and_nothing_is_kept(self):
        self.fake.files = {"a1": (PDF, len(PDF) + 5)}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "Invoice-X-0001.pdf", len(PDF) + 5)])]
        rows = fetch.run(self.inbox, self.spool, 50)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertFalse((self.spool / fetch.stem("<m1@mail.test>")).exists())

    def test_html_where_a_pdf_should_be_is_failed(self):
        page = b"<html>enable JavaScript</html>"
        self.fake.files = {"a1": (page, len(page))}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "Invoice-X-0001.pdf", len(page))])]
        rows = fetch.run(self.inbox, self.spool, 50)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertIn("%PDF", rows[0]["detail"])

    def test_a_path_in_the_filename_cannot_leave_the_message_folder(self):
        self.fake.files = {"a1": (PDF, len(PDF))}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "../../evil.pdf", len(PDF))])]
        rows = fetch.run(self.inbox, self.spool, 50)
        self.assertEqual(rows[0]["filename"], "evil.pdf")
        self.assertTrue((self.spool / fetch.stem("<m1@mail.test>") / "evil.pdf").is_file())
        self.assertFalse((Path(self.tmp.name) / "evil.pdf").exists())

    def test_the_api_key_is_not_sent_to_the_download_link(self):
        self.fake.files = {"a1": (PDF, len(PDF))}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "Invoice-X-0001.pdf", len(PDF))])]
        fetch.run(self.inbox, self.spool, 50)
        self.assertEqual(self.fake.auth_on_download, [None])

    def test_messages_without_attachments_add_no_rows(self):
        self.fake.messages = [message("<m1@mail.test>", None)]
        self.assertEqual(fetch.run(self.inbox, self.spool, 50), [])

    def test_main_needs_the_key_and_reports_failures_in_its_status(self):
        self.fake.files = {"a1": (b"nope", 4)}
        self.fake.messages = [message("<m1@mail.test>", [att("a1", "Invoice-X-0001.pdf", 4)])]
        base = ["--inbox", "box@agentmail.test", "--spool", str(self.spool),
                "--base-url", f"http://127.0.0.1:{self.srv.server_port}"]
        import os
        os.environ.pop("AGENTMAIL_API_KEY", None)
        self.assertEqual(fetch.main(base), 2)
        os.environ["AGENTMAIL_API_KEY"] = KEY
        self.addCleanup(os.environ.pop, "AGENTMAIL_API_KEY", None)
        self.assertEqual(fetch.main(base), 1)


if __name__ == "__main__":
    unittest.main()
