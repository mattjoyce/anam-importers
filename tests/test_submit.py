"""anam_submit's own checks, before it reaches Anam."""

import contextlib
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from tests.helpers import run_plugin

SUBMIT = Path(__file__).resolve().parent.parent / "anam_submit" / "run.py"
BATCH = {"type": "anam_withings.batch", "payload": {"envelopes": [{"type": "t", "definition_version": 1, "payload": {}}]}}


class TokenSecretTest(unittest.TestCase):
    def handle(self, config, secrets):
        return run_plugin(SUBMIT, {"command": "handle", "config": config, "secrets": secrets, "event": BATCH})

    def test_the_token_is_the_secret_config_names_and_nothing_else(self):
        cases = [
            ("no token_secret", {"anam_url": "http://127.0.0.1:9"}, {"anam_importer_token_withings": "t"},
             "no token_secret"),
            ("the named secret not granted", {"anam_url": "http://127.0.0.1:9", "token_secret": "anam_importer_token_withings"},
             {"anam_importer_token_other": "t"}, "no anam_importer_token_withings secret"),
        ]
        for name, config, secrets, want in cases:
            with self.subTest(name):
                r = self.handle(config, secrets)
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"])
                self.assertIn(want, r["error"])


@contextlib.contextmanager
def daemon(status):
    """A loopback stand-in for Anam that answers GET /v1/status with status (None:
    a 404) and records every request: (method, path, JSON body or None)."""
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def answer(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            seen.append(("GET", self.path, None))
            if self.path == "/v1/status" and status is not None:
                self.answer(200, status)
            else:
                self.answer(404, {"error": "not here"})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            seen.append(("POST", self.path, body))
            n = len(body["envelopes"])
            self.answer(200, {"w": 7, "changed": n,
                              "results": [{"index": i, "outcome": "admitted", "facet_id": f"f{i}"} for i in range(n)]})

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


# What GET /v1/status answers before and after anam card 270a: v0.794 names the record's
# owner person only and refuses asserted_subject; v0.807 names subject, and person beside it.
BEFORE_270A = {"ledger_id": "l", "w": 1, "person": "person-a"}
AFTER_270A = {"ledger_id": "l", "w": 1, "subject": "person-a", "person": "person-a"}


class WireNameTest(unittest.TestCase):
    """The importers write asserted_subject (anam card 270a). anam_submit sends it under
    the name the daemon it reaches reads, so a rollback of Anam to a build from before
    270a does not refuse every batch."""

    def submit(self, url, envelopes):
        return run_plugin(SUBMIT, {"command": "handle", "config": {"anam_url": url, "token_secret": "t", "timeout": 2},
                                   "secrets": {"t": "synthetic-test-token-not-a-real-secret"},
                                   "event": {"payload": {"envelopes": envelopes}}})

    def posted(self, seen):
        return [body["envelopes"] for method, path, body in seen if method == "POST" and path == "/v1/envelopes"]

    def envs(self):
        return [{"type": "t", "definition_version": 1, "payload": {"id": "1"}, "asserted_subject": "person-a"},
                {"type": "t", "definition_version": 1, "payload": {"id": "2"}}]

    def test_a_daemon_that_answers_subject_gets_asserted_subject(self):
        with daemon(AFTER_270A) as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(self.posted(seen), [self.envs()])

    def test_a_daemon_from_before_270a_gets_asserted_person(self):
        with daemon(BEFORE_270A) as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "ok", r)
        [sent] = self.posted(seen)
        self.assertEqual(sent[0]["asserted_person"], "person-a")
        self.assertNotIn("asserted_subject", sent[0])
        self.assertEqual(sent[1], self.envs()[1], "an envelope that asserts no one is left as it is")

    def test_status_is_asked_once_and_only_when_an_envelope_asserts_a_subject(self):
        with daemon(AFTER_270A) as (url, seen):
            self.submit(url, self.envs() * 3)
        self.assertEqual([p for m, p, _ in seen if m == "GET"], ["/v1/status"])
        with daemon(AFTER_270A) as (url, seen):
            r = self.submit(url, self.envs()[1:])
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual([p for m, p, _ in seen if m == "GET"], [])

    def test_a_batch_queued_before_the_upgrade_still_goes(self):
        # An event an importer emitted before 270a carries asserted_person; both builds read it.
        old = [{"type": "t", "definition_version": 1, "payload": {"id": "1"}, "asserted_person": "person-a"}]
        for status in (BEFORE_270A, AFTER_270A):
            with self.subTest(status=status), daemon(status) as (url, seen):
                r = self.submit(url, old)
                self.assertEqual(r["status"], "ok", r)
                self.assertEqual(self.posted(seen), [old])

    def test_a_status_that_fails_is_a_retryable_error_and_nothing_is_posted(self):
        with daemon(None) as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "error", r)
        self.assertEqual(self.posted(seen), [])


if __name__ == "__main__":
    unittest.main()
