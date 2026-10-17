---
type: workflow
title: Check an importer against a real daemon
description: A test starts a real Anam daemon on a temporary ledger, shapes fixture rows with an importer, submits them through anam_submit, and asserts a second submit is all no-op.
timestamp: 2026-10-17T00:00:00Z
resource: tests/test_against_anam.py#test_withings_through_anam_submit
anchor: "def test_withings_through_anam_submit(self):"
basis: code
tier: supporting
trigger: A developer sets ANAM_BIN to an anam binary and runs the unit test command. Without the variable these tests skip.
steps:
  - actor: /components/test-harness.md
    caller: outside
    label: start a scratch daemon with one token
    action: "`Daemon` makes a temporary directory, a random importer token whose hash goes in an importers file, a free loopback port, and runs `anam init` then `anam daemon` on a new ledger and a new operational store. No test shares state with another."
    resource: tests/helpers.py#Daemon
    anchor: '"ANAM_IMPORTERS_FILE": str(d / "importers.yaml")'
  - actor: /components/test-harness.md
    label: run the importer's poll as a process
    action: "`run_plugin` writes the request to the plugin's stdin and parses its stdout, the same call the gateway makes. The input is a database built from made-up measurements."
    resource: tests/helpers.py#run_plugin
    anchor: "out = subprocess.run([sys.executable, str(entry)], input=json.dumps(request), capture_output=True, text=True,"
  - actor: /components/anam-submit.md
    caller: /components/test-harness.md
    label: submit the first batch event
    action: "The request carries the daemon's URL, a `token_secret` name, and the token under `secrets`."
    resource: tests/test_against_anam.py#submit
    anchor: '"secrets": {"anam_importer_token_test": self.daemon.token}'
  - actor: /components/anam-daemon.md
    caller: /components/anam-submit.md
    label: admit all three measurements
    action: "The first submit returns an ok result whose `anam.admitted` event reports three admitted."
    resource: tests/test_against_anam.py#test_withings_through_anam_submit
    anchor: 'self.assertEqual(first["events"][0]["payload"]["outcomes"], {"admitted": 3})'
  - actor: /components/anam-submit.md
    caller: /components/test-harness.md
    label: submit the same batch again
    action: "Nothing changed, so the importer's output is identical."
    resource: tests/test_against_anam.py#test_withings_through_anam_submit
    anchor: 'again = self.submit(shaped["events"][0])'
  - actor: /components/anam-daemon.md
    caller: /components/anam-submit.md
    label: answer no-op for every envelope
    action: "The assertion that all three are no-op is the test that a resend is safe, which every importer's design relies on."
    ends: true
    resource: tests/test_against_anam.py#test_withings_through_anam_submit
    anchor: 'self.assertEqual(again["events"][0]["payload"]["outcomes"], {"no-op": 3})'
---

Everything in these tests is made up. Account names, device ids, serials, coordinates and tokens are invented or generated per run, and no test reaches a network. The same pattern repeats per importer (blood pressure, Concept2, DreamStation, Garmin, OwnTracks, records, documents), each asserting that a resend is no-op. See [what is synthetic](/decisions/tests-use-real-components-and-invented-data.md).
