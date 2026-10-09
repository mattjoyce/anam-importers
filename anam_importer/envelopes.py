"""Envelopes and batches, in the shape POST /v1/envelopes takes them."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Iterator, List, Optional

from .definitions import Definition

# MAX_BATCH is the most envelopes one submission may carry: the gate's batch, one
# transaction.
MAX_BATCH = 49


class Invalid(ValueError):
    """Payloads that do not conform to their Definition. Each entry says which and why."""

    def __init__(self, problems: List[str]):
        super().__init__(f"{len(problems)} payload(s) do not conform: " + "; ".join(problems[:5]))
        self.problems = problems


def envelope(
    definition: Definition,
    payload: Dict[str, Any],
    asserted_person: Optional[str] = None,
) -> Dict[str, Any]:
    """One envelope for payload, shaped to definition. It names no source and no
    source_ref: the token names the source, and the gate composes identity."""
    env: Dict[str, Any] = {
        "type": definition.type,
        "definition_version": definition.version,
        "payload": payload,
    }
    if asserted_person:
        env["asserted_person"] = asserted_person
    return env


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
