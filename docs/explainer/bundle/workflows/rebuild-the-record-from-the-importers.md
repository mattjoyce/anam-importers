---
type: workflow
title: Rebuild the record from the importers
description: The rebuild drill runs each importer's poll, replays every batch into a scratch daemon on a new ledger, and compares the scratch ledger with a live one type by type.
timestamp: 2026-10-17T00:00:00Z
resource: scripts/rebuild-drill.py#main
anchor: "def main() -> None:"
basis: code
tier: supporting
trigger: An operator runs scripts/rebuild-drill.py with the anam binary, a plan, a work directory that does not exist, and optionally a live daemon to compare with.
steps:
  - actor: /components/rebuild-drill.md
    caller: outside
    label: run each importer's poll
    action: "For each plan entry, run `<plugin>/run.py` with the command `poll` and the plan's config, the same request the gateway sends. A non-ok result stops the drill."
    resource: scripts/rebuild-drill.py#main
    anchor: 'r = plugin(REPO / imp["plugin"] / "run.py", {"command": "poll", "config": imp["config"]})'
  - actor: /components/rebuild-drill.md
    label: collect the types each poll sent
    action: "The importers file for the scratch daemon is written from what the polls actually sent, so it needs no list of types."
    resource: scripts/rebuild-drill.py#main
    anchor: 'types = sorted({e["type"] for ev in r.get("events", []) for e in ev["payload"]["envelopes"]})'
  - actor: /components/rebuild-drill.md
    label: start a scratch daemon, a token each
    action: "`start` runs `anam init` and `anam daemon` on a new ledger in the work directory, pinned to the plan's person, answering reads whole (`ANAM_MAX_READ_BYTES` 0), and waits for `/healthz`."
    resource: scripts/rebuild-drill.py#start
    anchor: 'subprocess.run([anam, "init"], env=env, check=True, capture_output=True, timeout=60)'
  - actor: /components/anam-submit.md
    caller: /components/rebuild-drill.md
    label: send every batch as the gateway does
    action: "`submit` runs `anam_submit` for each event with a 300 second timeout and the importer's scratch token. A non-ok result stops the drill."
    resource: scripts/rebuild-drill.py#submit
    anchor: '"config": {"anam_url": url, "token_secret": "drill", "timeout": 300},'
  - actor: /components/anam-daemon.md
    caller: /components/anam-submit.md
    label: admit into the scratch ledger
    action: "Outcomes are summed per importer. On a rebuild from nothing the last submit of each says its snapshot completed and left no live facet absent."
    resource: scripts/rebuild-drill.py#submit
    anchor: 'for o, n in r["events"][0]["payload"]["outcomes"].items():'
  - actor: /components/rebuild-drill.md
    label: compare with the live daemon by type
    action: "For each type, read both timelines, halving the window by years while a read is too large. Keep only the plan's sources. Count facets in each, only in one, and those whose content hash or status differ."
    resource: scripts/rebuild-drill.py#compare
    anchor: '"differ": sorted(live[i]["source_ref"] for i in both'
  - actor: /components/rebuild-drill.md
    label: write report.json and stop the daemon
    action: "The report holds outcomes, the comparison and seconds per step. The work directory holds a copy of the record, so it should be deleted afterwards."
    ends: true
    resource: scripts/rebuild-drill.py#main
    anchor: '(args.work / "report.json").write_text(json.dumps(report, indent=1))'
---

A clean drill is zero in the last three columns for every type. A fact only in the live record is a source that no longer holds it, expected for a retired source and a bug otherwise. A fact only in the scratch ledger is one the live record retracted that the source still holds. A difference means the importer now shapes a payload differently from when it was admitted, and a resend to the live daemon would supersede it. See `docs/rebuild-drill.md`.
