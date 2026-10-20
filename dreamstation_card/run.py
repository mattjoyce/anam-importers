#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "jsonschema>=4.18",
#   "dreamstation @ https://github.com/mattjoyce/dreamstation/archive/refs/tags/v0.1.0.zip",
# ]
# ///
"""anam_dreamstation: shapes a Philips DreamStation SD card copy into
health.cpap-session.dreamstation envelopes for Anam, one batch event at a time.

The card holds every session since the device was first used, so a newer copy is
a superset of an older one and every run resends the whole card; Anam makes that
idempotent. The `dreamstation` package decodes the card. This shapes what the
device wrote and nothing else: the summary file's times, settings, pressure
summary and counts, and a tally of the events file. AHI and the other indexes,
and anything per night, are reads over these facets, not facts in them. The
.005 waveforms never leave the card.

Commands:
- handle : on a folder_watch event for the card copy, the whole card
- poll   : the whole card, in batches: the resend-everything mode
- health : the card decodes and every session conforms
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import Definition, batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402

TYPE = "health.cpap-session.dreamstation"
BATCH_EVENT = "anam_dreamstation.batch"

# The summary record's keys the Definition holds, as the decoder names them. Its
# derived figures (end, mask-on total, AHI, RDI, leak statistics, span totals) are
# left out: each is a read over these. Not configurable: the Definition decides.
KEPT = ("settings", "pressure", "device_counts")


def read(card_path: str):
    """The decoded card. A card the decoder cannot read is not retried: a new slice
    code or an unexpected size is a decision for a person, not a guess."""
    path = Path(card_path)
    if not path.exists():
        raise ductile.Failure(f"no card copy at {card_path}", retry=False)
    try:
        from dreamstation import FormatError, UnsupportedDeviceError, read_card
    except ImportError as exc:
        raise ductile.Failure(f"the dreamstation package is not installed: {exc}", retry=False) from exc
    try:
        return read_card(path)
    except (FormatError, UnsupportedDeviceError) as exc:
        raise ductile.Failure(f"card {card_path}: {exc}", retry=False) from exc
    except OSError as exc:
        raise ductile.Failure(f"card {card_path}: {exc}", retry=True) from exc


def payload(device, session) -> Dict[str, Any]:
    """One session as the device recorded it."""
    full = session.to_dict()
    p: Dict[str, Any] = {
        "device_serial": device.serial,
        "device_model": device.model,
        "device_software": device.software_version,
        "session": session.number,
        "start": full["start"],
        "duration_seconds": full["duration_seconds"],
        "mask_on_spans": full["mask_on_spans"],
    }
    for key in KEPT:
        if key in full:
            p[key] = full[key]
    counts = full.get("event_counts")
    if counts:
        p["event_counts"] = counts
    return {k: v for k, v in p.items() if v not in (None, "")}


def batch_events(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions: Dict[str, Definition] = load(HERE)
    definition = definitions[TYPE]
    card = read(str(config["card_path"]))
    person = str(config["person_id"])
    envs = [envelope(definition, payload(card.device, s), asserted_person=person) for s in card.sessions]
    check(definitions, envs)
    groups = list(batches(envs))
    manifest = definition.body.decode()
    # The card holds every session the device recorded, so a run is a snapshot, unless
    # the decoder skipped a file. A skipped file is an events file whose summary is not
    # on the card: part of a session this run cannot send, which Anam would otherwise
    # call absent. (A file the decoder cannot read fails the whole run instead.)
    whole = not card.skipped_files
    parts = snapshot_parts(len(groups), [TYPE]) if groups and whole else [None] * len(groups)
    events = []
    for i, (g, part) in enumerate(zip(groups, parts)):
        batch: Dict[str, Any] = {"envelopes": g, "definitions": [manifest], "batch": f"{i + 1}/{len(groups)}"}
        if part is not None:
            batch["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, batch))
    logs: List[str] = [f"skipped {f}" for f in card.skipped_files]
    return ductile.ok(f"{len(envs)} session(s) in {len(groups)} batch(es)", events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    return batch_events(request)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    return batch_events(request)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    definitions = load(HERE)
    card = read(str(config["card_path"]))
    envs = [envelope(definitions[TYPE], payload(card.device, s)) for s in card.sessions]
    check(definitions, envs)
    skipped = (f"; {len(card.skipped_files)} events file(s) without a summary, so a run is no snapshot: "
               + ", ".join(card.skipped_files[:5])) if card.skipped_files else ""
    return ductile.ok(f"{len(envs)} session(s) from {card.device.model}, every one conforming to "
                      f"{TYPE} v{definitions[TYPE].version}{skipped}")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
