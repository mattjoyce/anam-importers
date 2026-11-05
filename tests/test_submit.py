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


# What GET /v1/status answers before and after anam card 270a: v0.794 names the record's
# owner person only and refuses asserted_subject; v0.807 names subject, and person beside it.
BEFORE_270A = {"ledger_id": "l", "w": 1, "person": "person-a"}
AFTER_270A = {"ledger_id": "l", "w": 1, "subject": "person-a", "person": "person-a"}

# How each build answers POST /v1/envelopes for an envelope naming asserted_subject.
UNKNOWN_FIELD = 'submission: json: unknown field "asserted_subject"'


@contextlib.contextmanager
def daemon(builds, status_fails=None):
    """A loopback stand-in for Anam, as builds says. builds is "old" (before 270a) or
    "new", or a list of them: each GET /v1/status answers as the build in force, then
    the next build in the list takes over, which is a deploy or a rollback landing right
    after the read. status_fails, if set, is how every status read fails instead: an
    HTTP status, "malformed" or "disconnect". A "liar" answers status as 270a and
    takes envelopes as a build before it, as a proxy in front of the wrong daemon might. Records (method, path, JSON body or None)."""
    seen = []
    queue = [builds] if isinstance(builds, str) else list(builds)

    class Handler(BaseHTTPRequestHandler):
        def answer(self, code, body):
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            seen.append(("GET", self.path, None))
            if self.path != "/v1/status":
                return self.answer(404, {"error": "not here"})
            if status_fails == "disconnect":
                self.close_connection = True
                return
            if status_fails == "malformed":
                return self.answer(200, [])
            if status_fails is not None:
                return self.answer(status_fails, {"error": "injected"})
            build = queue[0]
            if len(queue) > 1:
                queue.pop(0)
            self.answer(200, BEFORE_270A if build == "old" else AFTER_270A)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            seen.append(("POST", self.path, body))
            envs = body["envelopes"]
            if queue[0] in ("old", "liar") and any("asserted_subject" in e for e in envs):
                return self.answer(400, {"error": UNKNOWN_FIELD})
            for i, e in enumerate(envs):
                if "asserted_subject" in e and e.get("asserted_person", e["asserted_subject"]) != e["asserted_subject"]:
                    return self.answer(400, {"error": f"envelope {i} (t): asserted_subject and asserted_person differ"})
            self.answer(200, {"w": 7, "changed": len(envs),
                              "results": [{"index": i, "outcome": "admitted", "facet_id": f"f{i}"} for i in range(len(envs))]})

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


def env(i, **fields):
    return {"type": "t", "definition_version": 1, "payload": {"id": str(i)}, **fields}


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

    def calls(self, seen):
        return [(m, p) for m, p, _ in seen]

    def envs(self):
        return [env(1, asserted_subject="person-a"), env(2)]

    def test_a_daemon_that_answers_subject_gets_asserted_subject(self):
        with daemon("new") as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(self.posted(seen), [self.envs()])

    def test_a_daemon_from_before_270a_gets_asserted_person(self):
        with daemon("old") as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "ok", r)
        [sent] = self.posted(seen)
        self.assertEqual(sent[0]["asserted_person"], "person-a")
        self.assertNotIn("asserted_subject", sent[0])
        self.assertEqual(sent[1], self.envs()[1], "an envelope that asserts no one is left as it is")

    def test_both_names_equal_go_to_an_old_daemon_as_asserted_person_alone(self):
        # Sol's review, finding 1: left with asserted_subject beside it, the old build
        # refuses the whole batch, its neighbours included.
        both = [env(1, asserted_subject="person-a", asserted_person="person-a"), env(2, asserted_subject="person-a")]
        with daemon("old") as (url, seen):
            r = self.submit(url, both)
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(self.posted(seen), [[env(1, asserted_person="person-a"), env(2, asserted_person="person-a")]])

    def test_both_names_that_differ_are_sent_as_they_are_and_refused(self):
        # Neither value is dropped: the gate cannot tell which the source meant, and
        # neither can anam_submit. Each build refuses the batch, nothing is admitted.
        conflict = [env(1, asserted_subject="person-a", asserted_person="other")]
        for build in ("old", "new"):
            with self.subTest(build=build), daemon(build) as (url, seen):
                r = self.submit(url, conflict)
                self.assertEqual(r["status"], "error", r)
                self.assertFalse(r["retry"], r)
                self.assertTrue(self.posted(seen), "the batch reaches the gate")
                self.assertTrue(all(sent == conflict for sent in self.posted(seen)), self.posted(seen))

    def test_status_is_asked_once_and_only_when_an_envelope_asserts_a_subject(self):
        with daemon("new") as (url, seen):
            self.submit(url, self.envs() * 3)
        self.assertEqual([p for m, p, _ in seen if m == "GET"], ["/v1/status"])
        with daemon("new") as (url, seen):
            r = self.submit(url, self.envs()[1:])
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual([p for m, p, _ in seen if m == "GET"], [])

    def test_a_batch_queued_before_the_upgrade_still_goes(self):
        # An event an importer emitted before 270a carries asserted_person; both builds read it.
        old = [env(1, asserted_person="person-a")]
        for build in ("old", "new"):
            with self.subTest(build=build), daemon(build) as (url, seen):
                r = self.submit(url, old)
                self.assertEqual(r["status"], "ok", r)
                self.assertEqual(self.posted(seen), [old])

    def test_every_status_failure_is_retryable_and_posts_no_envelopes(self):
        # Sol's review, finding 2: the status read is a question about the daemon, not
        # about the batch, so no answer to it is a reason to throw the batch away.
        for failure in (404, 401, 403, 400, 429, 500, 503, "malformed", "disconnect"):
            with self.subTest(failure=failure), daemon("new", status_fails=failure) as (url, seen):
                r = self.submit(url, self.envs())
                self.assertEqual(r["status"], "error", r)
                self.assertTrue(r["retry"], r)
                self.assertEqual(self.posted(seen), [])

    def test_a_rollback_between_the_status_read_and_the_post_is_renegotiated_once(self):
        # Sol's review, finding 3: status answers as 270a, then the old build takes the POST.
        with daemon(["new", "old"]) as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "ok", r)
        self.assertEqual(self.calls(seen), [("GET", "/v1/status"), ("POST", "/v1/envelopes"),
                                            ("GET", "/v1/status"), ("POST", "/v1/envelopes")])
        first, second = self.posted(seen)
        self.assertEqual(first, self.envs())
        self.assertEqual(second, [env(1, asserted_person="person-a"), env(2)])

    def test_a_daemon_that_keeps_refusing_after_renegotiation_is_retried_later(self):
        # The status says 270a both times, yet the POST is refused for the field: one
        # renegotiation, then a retryable error, never a loop.
        with daemon("liar") as (url, seen):
            r = self.submit(url, self.envs())
        self.assertEqual(r["status"], "error", r)
        self.assertTrue(r["retry"], r)
        self.assertIn("asserted_subject", r["error"])
        self.assertEqual(self.calls(seen), [("GET", "/v1/status"), ("POST", "/v1/envelopes"),
                                            ("GET", "/v1/status")])

if __name__ == "__main__":
    unittest.main()
