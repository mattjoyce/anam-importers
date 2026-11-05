"""Envelopes and batches, in the shape POST /v1/envelopes takes them."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

from .definitions import Definition

# MAX_BATCH is the most envelopes one submission may carry: the gate's batch, one
# transaction. Not configurable: Anam refuses a larger batch (its gate.MaxBatch), so
# both sides must agree. If Anam makes its cap a key, this becomes a default.
MAX_BATCH = 49


class Invalid(ValueError):
    """Payloads that do not conform to their Definition. Each entry says which and why."""

    def __init__(self, problems: List[str]):
        super().__init__(f"{len(problems)} payload(s) do not conform: " + "; ".join(problems[:5]))
        self.problems = problems


def envelope(
    definition: Definition,
    payload: Dict[str, Any],
    asserted_subject: Optional[str] = None,
) -> Dict[str, Any]:
    """One envelope for payload, shaped to definition. It names no source and no
    source_ref: the token names the source, and the gate composes identity."""
    env: Dict[str, Any] = {
        "type": definition.type,
        "definition_version": definition.version,
        "payload": payload,
    }
    if asserted_subject:
        env["asserted_subject"] = asserted_subject
    return env


def asserts_a_subject(envelopes: Iterable[Dict[str, Any]]) -> bool:
    """Whether any envelope carries asserted_subject, the name Anam reads since its
    card 270a."""
    return any("asserted_subject" in env for env in envelopes)


def for_a_daemon_before_270a(envelopes: List[Dict[str, Any]]) -> None:
    """Rename asserted_subject to asserted_person, its name before anam card 270a, in
    place. A daemon from before 270a refuses a field it does not know, so a batch for
    one carries the old name. An envelope naming both with one value keeps
    asserted_person alone. One naming two values is left as it is, for the gate to
    refuse: nothing here can tell which the source meant. Remove once no daemon before
    270a is kept to roll back to."""
    for env in envelopes:
        if "asserted_subject" not in env:
            continue
        if env.setdefault("asserted_person", env["asserted_subject"]) == env["asserted_subject"]:
            del env["asserted_subject"]


def refused_for_asserted_subject(exc: Exception) -> bool:
    """Whether exc is a daemon from before anam card 270a refusing asserted_subject as
    a field it does not know: a 400 naming it."""
    return getattr(exc, "status", None) == 400 and 'unknown field "asserted_subject"' in str(exc)


def check(definitions: Dict[str, Definition], envelopes: Iterable[Dict[str, Any]]) -> None:
    """Raise Invalid unless every envelope's payload conforms to its Definition, so
    a refusal at the gate means the importer and Anam disagree, not a bad row."""
    problems: List[str] = []
    for i, env in enumerate(envelopes):
        d = definitions.get(env["type"])
        if d is None:
            problems.append(f"envelope {i}: no Definition for {env['type']} in this importer")
            continue
        problems.extend(f"envelope {i} ({env['type']}): {e}" for e in d.errors(env["payload"]))
    if problems:
        raise Invalid(problems)


def batches(envelopes: List[Dict[str, Any]], size: int = MAX_BATCH) -> Iterator[List[Dict[str, Any]]]:
    """envelopes in batches of at most size, in order."""
    if not 1 <= size <= MAX_BATCH:
        raise ValueError(f"batch size {size} is outside 1..{MAX_BATCH}")
    for start in range(0, len(envelopes), size):
        yield envelopes[start : start + size]


def snapshot_parts(count: int, types: Sequence[str], run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """The snapshot label for each of a resend-everything run's count batches, in
    order. Only a run that sends everything the source holds of types may label
    itself so: Anam reports as absent whatever of those types it holds live from
    this source and the run did not carry. A fresh id per run unless one is given."""
    if count < 1:
        raise ValueError("a snapshot has at least one part")
    sid = run_id or f"run-{uuid.uuid4()}"
    kinds = sorted(set(types))
    return [{"id": sid, "part": i + 1, "parts": count, "types": kinds} for i in range(count)]
