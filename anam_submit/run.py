#!/usr/bin/env python3
"""anam_submit: posts one batch of envelopes to Anam under one importer's token.

It knows Anam's endpoint and nothing about any source. An importer emits a batch
event carrying its envelopes and the Definitions they were shaped to; this makes
sure Anam publishes those Definitions, then submits the batch. One instance per
importer, each holding that importer's token, so a token never leaves the plugin
that uses it.

Commands:
- handle : submit the triggering event's batch; when it is the part that completes a
           snapshot and Anam reports facets absent, raise anam.snapshot_absent. A batch
           may name documents ({path, file}): their bytes are handed to Anam's library
           first (POST /v1/documents), read from file, so bytes never ride in an event.
           Anam names each stored file by its sha256; the path lends it an extension
- health : ask Anam for its Definitions under the token
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from anam_importer import Client, Refused, ensure_published, parse  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402
from anam_importer.client import DEFAULT_MAX_RESPONSE, DEFAULT_TIMEOUT  # noqa: E402

# ABSENT_IDS_SHOWN is how many absent facet ids the alert carries unless config's
# absent_ids_shown says otherwise. The report holds up to MAX_ABSENT_IDS, and anam
# retract lists them all.
ABSENT_IDS_SHOWN = 20

# MAX_ABSENT_IDS is the most absent ids Anam's snapshot report holds (its
# api.AbsentIDsMax), so the most an alert can carry. Not configurable: it is Anam's.
MAX_ABSENT_IDS = 1000


class Settings(NamedTuple):
    """This instance's config, read and checked once, at the start of a command."""

    timeout: float
    max_response: int
    absent_ids_shown: int


def settings(config: Dict[str, Any]) -> Settings:
    return Settings(
        timeout=cfg.number(config, "timeout", DEFAULT_TIMEOUT, 0, 3600, low_open=True),
        max_response=cfg.integer(config, "max_response_bytes", DEFAULT_MAX_RESPONSE, 1, 1 << 30),
        absent_ids_shown=cfg.integer(config, "absent_ids_shown", ABSENT_IDS_SHOWN, 0, MAX_ABSENT_IDS),
    )


def client_of(request: Dict[str, Any], s: Settings) -> Client:
    """A client under the token in the secret config names. Vault secret names are
    global, so each instance names its importer's own: token_secret."""
    config = request.get("config") or {}
    name = str(config.get("token_secret", ""))
    if not name:
        raise ValueError("no token_secret in this instance's config")
    token = (request.get("secrets") or {}).get(name, "")
    if not token:
        raise ValueError(f"no {name} secret granted to this instance")
    return Client(str(config["anam_url"]), token, s.timeout, s.max_response)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    s = settings(request.get("config") or {})
    batch = ductile.payload_of(request)
    envelopes: List[Dict[str, Any]] = batch.get("envelopes") or []
    if not envelopes:
        return ductile.error("the event carries no envelopes", retry=False)
    client = client_of(request, s)
    for doc in batch.get("documents") or []:
        try:
            data = Path(str(doc["file"])).read_bytes()
        except OSError as exc:
            return ductile.error(f"document {doc.get('path')}: {exc}", retry=True)
        client.store_document(str(doc["path"]), data)
    definitions = [parse(m.encode() if isinstance(m, str) else m) for m in batch.get("definitions") or []]
    ensure_published(client, definitions)
    if batch.get("current_versions"):
        stamp_current(client, envelopes)
    snapshot = batch.get("snapshot") or None
    try:
        admission = client.submit(envelopes, snapshot)
    except Refused as exc:
        reasons = [f"envelope {r.get('index')} ({r.get('type')}): {r.get('reason')}" for r in exc.refused]
        return ductile.error(f"batch refused, nothing admitted: {len(reasons)} envelope(s)", retry=False, logs=reasons)

    outcomes: Dict[str, int] = {}
    for r in admission.get("results", []):
        outcomes[r["outcome"]] = outcomes.get(r["outcome"], 0) + 1
    summary = ", ".join(f"{n} {o}" for o, n in sorted(outcomes.items()))
    events = [ductile.event("anam.admitted", {
        "w": admission.get("w"), "changed": admission.get("changed"), "outcomes": outcomes,
        "batch": batch.get("batch"),
    })]
    if snapshot and (admission.get("snapshot") or {}).get("complete"):
        report = client.snapshot(str(snapshot["id"]))
        summary += f"; snapshot complete, {report.get('absent', 0)} of {report.get('live', 0)} live absent"
        if report.get("absent"):
            events.append(absent_event(snapshot, report, s.absent_ids_shown))
    return ductile.ok(f"{summary} at W {admission.get('w')}", events=events)


def stamp_current(client: Client, envelopes: List[Dict[str, Any]]) -> None:
    """Shape each envelope that names no version to its type's current one, as Anam
    publishes it. Only a batch that asks for it (current_versions) gets this: a source
    with no version of its own, such as a records file, which Anam's built-in worker
    always admitted at the current version. A type Anam does not publish is left to
    the gate to refuse."""
    current = {d["type"]: d["current"] for d in client.definitions()}
    for env in envelopes:
        if "definition_version" not in env and env.get("type") in current:
            env["definition_version"] = current[env["type"]]


def absent_event(snapshot: Dict[str, Any], report: Dict[str, Any], shown: int) -> Dict[str, Any]:
    """The alert that a complete resend did not carry facets Anam holds live. Nothing
    is retracted: the operator decides, with anam retract. Keyed on the snapshot, so
    a resent last part does not alert twice."""
    return ductile.event("anam.snapshot_absent", {
        "snapshot": snapshot["id"], "types": snapshot.get("types", []),
        "absent": report.get("absent"), "live": report.get("live"), "carried": report.get("carried"),
        "absent_ids": (report.get("absent_ids") or [])[:shown],
    }, dedupe_key=f"anam.snapshot_absent:{snapshot['id']}")


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    published = client_of(request, settings(request.get("config") or {})).definitions()
    return ductile.ok(f"Anam publishes {len(published)} Definitions")


if __name__ == "__main__":
    ductile.run({"handle": handle, "health": health})
