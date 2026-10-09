#!/usr/bin/env python3
"""anam_submit: posts one batch of envelopes to Anam under one importer's token.

It knows Anam's endpoint and nothing about any source. An importer emits a batch
event carrying its envelopes and the Definitions they were shaped to; this makes
sure Anam publishes those Definitions, then submits the batch. One instance per
importer, each holding that importer's token, so a token never leaves the plugin
that uses it.

Commands:
- handle : submit the triggering event's batch
- health : ask Anam for its Definitions under the token
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anam_importer import Client, Refused, ensure_published, parse  # noqa: E402
from anam_importer import ductile  # noqa: E402

def client_of(request: Dict[str, Any]) -> Client:
    """A client under the token in the secret config names. Vault secret names are
    global, so each instance names its importer's own: token_secret."""
    config = request.get("config") or {}
    name = str(config.get("token_secret", ""))
    if not name:
        raise ValueError("no token_secret in this instance's config")
    token = (request.get("secrets") or {}).get(name, "")
    if not token:
        raise ValueError(f"no {name} secret granted to this instance")
    return Client(str(config["anam_url"]), token, float(config.get("timeout", 30)))


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    batch = ductile.payload_of(request)
    envelopes: List[Dict[str, Any]] = batch.get("envelopes") or []
    if not envelopes:
        return ductile.error("the event carries no envelopes", retry=False)
    client = client_of(request)
    definitions = [parse(m.encode() if isinstance(m, str) else m) for m in batch.get("definitions") or []]
    ensure_published(client, definitions)
    try:
        admission = client.submit(envelopes)
    except Refused as exc:
        reasons = [f"envelope {r.get('index')} ({r.get('type')}): {r.get('reason')}" for r in exc.refused]
        return ductile.error(f"batch refused, nothing admitted: {len(reasons)} envelope(s)", retry=False, logs=reasons)

    outcomes: Dict[str, int] = {}
    for r in admission.get("results", []):
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    summary = ", ".join(f"{n} {o}" for o, n in sorted(outcomes.items()))
    return ductile.ok(
        f"{summary} at W {admission.get('w')}",
        events=[ductile.event("anam.admitted", {
            "w": admission.get("w"), "changed": admission.get("changed"), "outcomes": outcomes,
            "batch": batch.get("batch"),
        })],
    )


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    published = client_of(request).definitions()
    return ductile.ok(f"Anam publishes {len(published)} Definitions")


if __name__ == "__main__":
    ductile.run({"handle": handle, "health": health})
