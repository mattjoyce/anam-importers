#!/usr/bin/env python3
"""Rebuild the record from its sources, as a drill (anam card 141).

Starts a scratch `anam daemon` on a fresh ledger, runs each importer in the plan
through its resend-everything `poll` and `anam_submit`, exactly as the gateway would,
then compares the scratch ledger with a live daemon, type by type: for each source in
the plan, the facet ids each ledger holds, and each facet's content hash and status.
It writes nothing to the live daemon; it only reads its timeline.

    rebuild-drill.py --anam BIN --plan plan.json --work DIR \\
        [--live-url URL --live-token-file FILE]

The plan is JSON (see docs/rebuild-drill.md):

    {"person_id": "...",
     "importers": [{"source": "records", "plugin": "records",
                    "config": {"records_dir": "...", "person_id": "..."}}, ...]}

`plugin` is the importer's folder in this repository; `config` is its instance config,
as the gateway gives it. Each importer's types are the ones its poll emits, so the
scratch daemon's importers file is written from what the run sends. The work
directory must not exist; it keeps the scratch ledger, the daemon's log and
report.json. Stdlib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO = Path(__file__).resolve().parent.parent

# PLUGIN_TIMEOUT bounds one plugin run. A whole Garmin or DreamStation poll reads
# every file it holds, which takes minutes over a network share.
PLUGIN_TIMEOUT = 3600


def plugin(entry: Path, request: Dict[str, Any]) -> Dict[str, Any]:
    """One ductile invocation of entry: the request on stdin, the response from
    stdout. The entrypoint runs by its own shebang, so a uv script gets its
    dependencies as it does on the gateway."""
    out = subprocess.run([str(entry)], input=json.dumps(request), capture_output=True, text=True,
                         timeout=PLUGIN_TIMEOUT, check=False)
    if out.returncode != 0:
        raise SystemExit(f"{entry}: exit {out.returncode}: {out.stderr.strip()[-2000:]}")
    return json.loads(out.stdout)


def get(url: str, token: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=300) as r:  # noqa: S310 - a URL the operator names
        return json.load(r)


def entries(base: str, token: str, typ: str) -> List[Dict[str, Any]]:
    """Every current entry of typ, halving the window by years while a read is over
    the daemon's max_read_bytes (413)."""
    def window(lo: Optional[int], hi: Optional[int]) -> List[Dict[str, Any]]:
        q = {"zone": "UTC", "type": typ}
        if lo is not None:
            q["from"], q["to"] = f"{lo}-01-01", f"{hi}-01-01"
        try:
            return get(base + "/v1/timeline?" + urllib.parse.urlencode(q), token).get("entries", [])
        except urllib.error.HTTPError as e:
            if e.code != 413:
                raise
        lo, hi = (1900, 2100) if lo is None else (lo, hi)
        if hi - lo <= 1:
            raise SystemExit(f"{typ}: one year is still over the daemon's max_read_bytes")
        mid = (lo + hi) // 2
        return window(lo, mid) + window(mid, hi)
    return window(None, None)


def start(anam: str, work: Path, person: str, importers: Dict[str, Dict[str, Any]]) -> tuple:
    """A scratch daemon on a fresh ledger in work, accepting each importer under a
    token of its own. It answers reads whole (max_read_bytes 0)."""
    (work / "importers.yaml").write_text("importers:\n" + "".join(
        f"  - source: {s}\n    token_sha256: {hashlib.sha256(i['token'].encode()).hexdigest()}\n"
        f"    types: [{', '.join(i['types'])}]\n" for s, i in importers.items()))
    operator = secrets.token_hex(24)
    (work / "token").write_text(operator)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**{k: v for k, v in os.environ.items() if not k.startswith("ANAM_")},
           "ANAM_PERSON_ID": person, "ANAM_LEDGER_PATH": str(work / "ledger.db"),
           "ANAM_DB_PATH": str(work / "tracking.db"), "ANAM_ARTIFACT_DIR": str(work / "artifacts"),
           "ANAM_LISTEN": f"127.0.0.1:{port}", "ANAM_TOKEN_FILE": str(work / "token"),
           "ANAM_IMPORTERS_FILE": str(work / "importers.yaml"), "ANAM_ZONE": "UTC",
           "ANAM_MAX_READ_BYTES": "0", "ANAM_TIMEOUT": "60s"}
    subprocess.run([anam, "init"], env=env, check=True, capture_output=True, timeout=60)
    log = open(work / "daemon.log", "w")  # noqa: SIM115 - held for the daemon's life
    proc = subprocess.Popen([anam, "daemon"], env=env, stdout=log, stderr=log)
    url = f"http://127.0.0.1:{port}"
    for _ in range(300):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=1)  # noqa: S310 - loopback
            return proc, url, operator
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise SystemExit("the scratch daemon did not become ready; see daemon.log")


def submit(url: str, token: str, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Every batch event through anam_submit, as the gateway runs it."""
    outcomes: Dict[str, int] = {}
    last = ""
    for ev in events:
        r = plugin(REPO / "anam_submit/run.py", {
            "command": "handle", "event": ev,
            "config": {"anam_url": url, "token_secret": "drill", "timeout": 300},
            "secrets": {"drill": token}})
        if r.get("status") != "ok":
            raise SystemExit(f"submit: {r}")
        for o, n in r["events"][0]["payload"]["outcomes"].items():
            outcomes[o] = outcomes.get(o, 0) + n
        last = r.get("result", "")
    return {"outcomes": outcomes, "last": last}


def compare(scratch_url: str, scratch_token: str, live_url: str, live_token: str,
            sources: set, types: List[str]) -> Dict[str, Any]:
    out = {}
    for typ in types:
        scratch = {e["facet_id"]: e for e in entries(scratch_url, scratch_token, typ) if e["source"] in sources}
        live = {e["facet_id"]: e for e in entries(live_url, live_token, typ) if e["source"] in sources}
        both = set(live) & set(scratch)
        out[typ] = {
            "live": len(live), "scratch": len(scratch),
            "only_live": sorted(live[i]["source_ref"] for i in set(live) - set(scratch)),
            "only_scratch": sorted(scratch[i]["source_ref"] for i in set(scratch) - set(live)),
            "differ": sorted(live[i]["source_ref"] for i in both
                             if (live[i]["content_hash"], live[i]["status"])
                             != (scratch[i]["content_hash"], scratch[i]["status"])),
        }
        c = out[typ]
        print(f"  {typ:32} live {c['live']:6}  scratch {c['scratch']:6}  only-live {len(c['only_live']):4}  "
              f"only-scratch {len(c['only_scratch']):4}  differ {len(c['differ']):4}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--anam", required=True, help="the anam binary to run the scratch daemon with")
    ap.add_argument("--plan", required=True, type=Path)
    ap.add_argument("--work", required=True, type=Path, help="a directory that does not exist yet")
    ap.add_argument("--live-url", help="the live daemon to compare with; without it, no comparison")
    ap.add_argument("--live-token-file", type=Path)
    args = ap.parse_args()
    if args.live_url and not args.live_token_file:
        ap.error("--live-url needs --live-token-file")
    plan = json.loads(args.plan.read_text())
    args.work.mkdir(parents=True, exist_ok=False)
    timings: Dict[str, float] = {}

    importers: Dict[str, Dict[str, Any]] = {}
    for imp in plan["importers"]:
        t = time.monotonic()
        r = plugin(REPO / imp["plugin"] / "run.py", {"command": "poll", "config": imp["config"]})
        timings[f"{imp['source']} poll"] = time.monotonic() - t
        if r.get("status") != "ok":
            raise SystemExit(f"{imp['source']} poll: {r}")
        types = sorted({e["type"] for ev in r.get("events", []) for e in ev["payload"]["envelopes"]})
        importers[imp["source"]] = {"events": r.get("events", []), "types": types, "token": secrets.token_hex(32)}
        print(f"{imp['source']}: {r.get('result')} {types}")

    proc, url, operator = start(args.anam, args.work, plan["person_id"], importers)
    try:
        report: Dict[str, Any] = {"importers": {}, "timings": timings}
        for source, imp in importers.items():
            t = time.monotonic()
            report["importers"][source] = submit(url, imp["token"], imp["events"])
            timings[f"{source} submit"] = time.monotonic() - t
            print(f"{source}: {report['importers'][source]['outcomes']} | {report['importers'][source]['last']}")
        report["scratch_w"] = get(url + "/v1/status", operator)["w"]
        if args.live_url:
            print("compare with", args.live_url)
            types = sorted({t for imp in importers.values() for t in imp["types"]})
            report["compare"] = compare(url, operator, args.live_url, args.live_token_file.read_text().strip(),
                                        set(importers), types)
        print("scratch W", report["scratch_w"], "| seconds", {k: round(v, 1) for k, v in timings.items()})
        (args.work / "report.json").write_text(json.dumps(report, indent=1))
    finally:
        proc.terminate()
        proc.wait(timeout=60)


if __name__ == "__main__":
    main()
