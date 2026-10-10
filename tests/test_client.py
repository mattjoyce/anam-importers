"""The client against hostile and broken servers (anam cards 112, 113, 115, 116, 117),
promoted from the blue team's pressure test of 2026-10-11. Loopback servers and
synthetic tokens only."""

from __future__ import annotations

import contextlib
import json
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from anam_importer import AnamError, Client
from anam_importer.client import admission
from tests.helpers import REPO, run_plugin

TOKEN = "synthetic-test-token-not-a-real-secret"
SUBMIT = REPO / "anam_submit" / "run.py"


@contextlib.contextmanager
def server(respond):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(dict(self.headers))
            respond(self)

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            seen.append(dict(self.headers))
            respond(self)

        def log_message(self, *args):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}", seen
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=2)


def reply(handler, body: bytes, status: int = 200):
    handler.send_response(status)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def submit_request(url: str) -> dict:
    return {"command": "handle", "config": {"anam_url": url, "token_secret": "t", "timeout": 2},
            "secrets": {"t": TOKEN},
            "event": {"payload": {"envelopes": [{"type": "test.reading", "definition_version": 1,
                                                 "payload": {"id": "x"}}]}}}


RECEIPT = {"w": 7, "changed": 1, "results": [{"index": 0, "outcome": "admitted", "facet_id": "f"}]}


class Redirects(unittest.TestCase):
    def test_no_redirect_is_followed_so_the_token_stays_on_its_origin(self):
        with server(lambda h: reply(h, b'{"definitions":[]}')) as (other, captured):
            for status in (301, 302, 303, 307, 308):
                for target in (other + "/capture", "https://127.0.0.2:1/x", other.replace("http:", "http:") + "/v1"):
                    with self.subTest(status=status, target=target):
                        def redirect(h, status=status, target=target):
                            h.send_response(status)
                            h.send_header("Location", target)
                            h.send_header("Content-Length", "0")
                            h.end_headers()

                        with server(redirect) as (origin, _):
                            with self.assertRaises(AnamError) as ctx:
                                Client(origin, TOKEN, timeout=2).definitions()
                        self.assertFalse(ctx.exception.retry)
                        self.assertIn("not followed", str(ctx.exception))
                        self.assertNotIn(TOKEN, str(ctx.exception))
        self.assertEqual(captured, [])

    def test_a_url_with_credentials_or_a_query_is_refused(self):
        for url in ("http://user:pw@127.0.0.1:1", "http://127.0.0.1:1/?x=1", "ftp://127.0.0.1", "http://"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                Client(url, TOKEN)


class Receipts(unittest.TestCase):
    def test_a_200_that_is_not_a_receipt_is_a_retryable_error_with_no_admitted_event(self):
        bodies = [b"upstream returned an HTML page", b"{}", b"[]", b"null",
                  json.dumps({**RECEIPT, "w": None}).encode(),
                  json.dumps({**RECEIPT, "results": []}).encode(),
                  json.dumps({**RECEIPT, "changed": 0}).encode(),
                  json.dumps({**RECEIPT, "results": [{"index": 1, "outcome": "admitted"}]}).encode(),
                  json.dumps({**RECEIPT, "results": [{"index": 0, "outcome": "kept"}]}).encode()]
        for body in bodies:
            with self.subTest(body=body), server(lambda h, b=body: reply(h, b)) as (url, _):
                r = run_plugin(SUBMIT, submit_request(url))
                self.assertEqual(r["status"], "error", r)
                self.assertTrue(r["retry"], r)
                self.assertNotIn("events", {k for k, v in r.items() if v})

    def test_a_receipt_is_accepted(self):
        self.assertEqual(admission(RECEIPT, 1), RECEIPT)
        with server(lambda h: reply(h, json.dumps(RECEIPT).encode())) as (url, _):
            r = run_plugin(SUBMIT, submit_request(url))
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(r["events"][0]["payload"]["outcomes"], {"admitted": 1})

    def test_a_refusal_is_still_not_retried(self):
        refusal = {"error": "1 refused", "refused": [{"index": 0, "type": "test.reading", "reason": "bad"}]}
        with server(lambda h: reply(h, json.dumps(refusal).encode(), 422)) as (url, _):
            r = run_plugin(SUBMIT, submit_request(url))
        self.assertEqual(r["status"], "error")
        self.assertFalse(r["retry"])

    def test_definitions_must_be_a_listing(self):
        for body in (b"{}", b'{"definitions": [{"type": "a.b"}]}', b"<html>"):
            with self.subTest(body=body), server(lambda h, b=body: reply(h, b)) as (url, _):
                with self.assertRaises(AnamError) as ctx:
                    Client(url, TOKEN, timeout=2).definitions()
                self.assertTrue(ctx.exception.retry)


class Transport(unittest.TestCase):
    def test_a_truncated_answer_is_retryable(self):
        def truncated(h):
            h.send_response(200)
            h.send_header("Content-Length", "100")
            h.end_headers()
            h.wfile.write(b'{"w":1')
            h.close_connection = True

        with server(truncated) as (url, _):
            r = run_plugin(SUBMIT, submit_request(url))
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(r["retry"], r)

    def test_the_timeout_is_a_total_deadline(self):
        def trickle(h):
            body = b'{"definitions":[]}'
            h.send_response(200)
            h.send_header("Content-Length", str(len(body)))
            h.end_headers()
            try:
                for byte in body:
                    h.wfile.write(bytes([byte]))
                    h.wfile.flush()
                    time.sleep(0.06)
            except (BrokenPipeError, ConnectionResetError):
                pass

        with server(trickle) as (url, _):
            began = time.monotonic()
            with self.assertRaises(AnamError) as ctx:
                Client(url, TOKEN, timeout=0.2).definitions()
            elapsed = time.monotonic() - began
        self.assertLess(elapsed, 0.6, f"a 0.2s budget took {elapsed:.3f}s")
        self.assertTrue(ctx.exception.retry)

    def test_the_deadline_header_keeps_its_fraction(self):
        with server(lambda h: reply(h, b'{"definitions":[]}')) as (url, seen):
            Client(url, TOKEN, timeout=0.25).definitions()
        self.assertEqual(seen[0]["Anam-Timeout"], "250ms")
        self.assertEqual(seen[0]["Authorization"], "Bearer " + TOKEN)

    def test_an_oversized_answer_is_refused(self):
        from anam_importer import client as mod

        old, mod.MAX_RESPONSE = mod.MAX_RESPONSE, 64
        try:
            with server(lambda h: reply(h, b'{"definitions":[' + b" " * 200 + b"]}")) as (url, _):
                with self.assertRaises(AnamError) as ctx:
                    Client(url, TOKEN, timeout=2).definitions()
            self.assertIn("larger than 64", str(ctx.exception))
        finally:
            mod.MAX_RESPONSE = old

    def test_a_chunked_answer_is_read_whole_and_a_cut_one_is_retryable(self):
        body = json.dumps({"definitions": [{"type": "a.b", "origin": "bundled", "current": 1, "versions": [1]}]})

        def chunked(h, cut=False):
            h.protocol_version = "HTTP/1.1"
            h.send_response(200)
            h.send_header("Transfer-Encoding", "chunked")
            h.end_headers()
            for part in (body[:10], body[10:]):
                h.wfile.write(f"{len(part):x}\r\n{part}\r\n".encode())
                if cut:
                    h.close_connection = True
                    return
            h.wfile.write(b"0\r\n\r\n")

        with server(chunked) as (url, _):
            self.assertEqual(Client(url, TOKEN, timeout=2).definitions()[0]["type"], "a.b")
        with server(lambda h: chunked(h, cut=True)) as (url, _):
            with self.assertRaises(AnamError) as ctx:
                Client(url, TOKEN, timeout=2).definitions()
            self.assertTrue(ctx.exception.retry)

    def test_a_path_under_the_url_is_kept(self):
        with server(lambda h: reply(h, b'{"definitions":[]}')) as (url, _):
            self.assertEqual(Client(url + "/", TOKEN, timeout=2).definitions(), [])


class Protocol(unittest.TestCase):
    def test_a_request_that_is_not_an_object_gets_a_structured_error(self):
        for body in ("[]", "null", "42", '"handle"'):
            with self.subTest(body=body):
                p = subprocess.run([sys.executable, str(SUBMIT)], input=body, capture_output=True, text=True,
                                   timeout=10)
                self.assertEqual(p.returncode, 0, p.stderr)
                out = json.loads(p.stdout)
                self.assertEqual(out["status"], "error")
                self.assertFalse(out["retry"])


if __name__ == "__main__":
    unittest.main()
