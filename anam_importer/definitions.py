"""An importer's Definitions: the JSON manifests in its folder, the contract it
shapes payloads to. They are Anam's manifest format, so a payload this module
accepts is one the gate accepts (docs/IMPORTERS.md §8 in the anam repo).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .client import AnamError, Client


@dataclass(frozen=True)
class Definition:
    """One manifest: its type, version and body as the file holds it."""

    type: str
    version: int
    body: bytes
    manifest: Dict[str, Any] = field(compare=False, repr=False)

    def errors(self, payload: Any) -> List[str]:
        """Every way payload fails the schema, or [] when it conforms. A verbatim
        Definition has no schema and accepts any payload."""
        schema = self.manifest.get("schema")
        if self.manifest["meta"].get("validation_mode") == "verbatim" or schema is None:
            return []
        from jsonschema import Draft202012Validator  # the importer's one dependency

        v = Draft202012Validator(schema)
        return sorted(f"{'/'.join(map(str, e.absolute_path)) or '(payload)'}: {e.message}" for e in v.iter_errors(payload))


def parse(body: bytes) -> Definition:
    """A Definition from a manifest's bytes."""
    manifest = json.loads(body)
    meta = manifest["meta"]
    return Definition(
        type=str(meta["facet_type"]), version=int(meta["definition_version"]), body=body, manifest=manifest
    )


class Definitions(dict):
    """An importer's Definitions: the current one of each type it emits, by type, and
    every version of those types it has emitted, oldest first (docs/IMPORTERS.md §8.3
    in the anam repo). A payload is shaped to the current one; every version is
    registered, so a rebuilt operational store holds the words each facet was
    admitted under."""

    def __init__(self, current: Dict[str, Definition], every: List[Definition]):
        super().__init__(current)
        self.every = every

    def manifests(self, types: Optional[List[str]] = None) -> List[str]:
        """The manifests to register, as text: every version of types (all of them
        when None), each type's oldest first, since Anam refuses a version older than
        one it holds."""
        wanted = set(self) if types is None else set(types)
        return [d.body.decode() for d in self.every if d.type in wanted]


def load(folder: Path) -> Definitions:
    """Every manifest in folder/definitions, by type, with the earlier versions of
    those types in folder/definitions/history/<type>.v<n>.json. Two current
    manifests for one type is an error: an importer shapes each type to one version
    at a time. A history file of a type the importer no longer emits, an old name
    a rename carried away, is Anam's history and not registered."""
    current: Dict[str, Definition] = {}
    for path in sorted((folder / "definitions").glob("*.json")):
        d = parse(path.read_bytes())
        if path.name != d.type + ".json":
            raise ValueError(f"{path}: declares {d.type}; name the file {d.type}.json")
        if d.type in current:
            raise ValueError(f"{path}: a second manifest for {d.type}")
        current[d.type] = d
    earlier: Dict[str, Dict[int, Definition]] = {t: {} for t in current}
    for path in sorted((folder / "definitions" / "history").glob("*.json")):
        d = parse(path.read_bytes())
        if path.name != f"{d.type}.v{d.version}.json":
            raise ValueError(f"{path}: declares {d.type} v{d.version}; name the file {d.type}.v{d.version}.json")
        if d.type not in current:
            continue
        if d.version >= current[d.type].version:
            raise ValueError(f"{path}: v{d.version} is not older than the current {d.type} "
                             f"v{current[d.type].version}")
        earlier[d.type][d.version] = d
    every = [d for t in sorted(current) for d in [*(earlier[t][v] for v in sorted(earlier[t])), current[t]]]
    return Definitions(current, every)


def ensure_published(client: Client, definitions: List[Definition]) -> None:
    """Make sure Anam publishes each Definition at its version, with the same body.

    A Definition Anam already holds is left alone, whether Anam's binary bundles it
    or an importer registered it; one it does not hold is registered. One it holds
    with another body is refused: the importer and Anam disagree about what that
    version means, and nothing should be submitted until they agree.
    """
    for d in definitions:
        published = client.definition(d.type, d.version)
        if published is None:
            client.register(d.body)
            continue
        if published != d.manifest:
            raise AnamError(f"{d.type} v{d.version}: Anam publishes another body at this version", retry=False)
