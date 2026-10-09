"""An importer's Definitions: the JSON manifests in its folder, the contract it
shapes payloads to. They are Anam's manifest format, so a payload this module
accepts is one the gate accepts (docs/IMPORTERS.md §8 in the anam repo).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

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


def load(folder: Path) -> Dict[str, Definition]:
    """Every manifest in folder/definitions, by type. Two for one type is an error:
    an importer shapes each type to one version at a time."""
    out: Dict[str, Definition] = {}
    for path in sorted((folder / "definitions").glob("*.json")):
        d = parse(path.read_bytes())
        if path.name != d.type + ".json":
            raise ValueError(f"{path}: declares {d.type}; name the file {d.type}.json")
        if d.type in out:
            raise ValueError(f"{path}: a second manifest for {d.type}")
        out[d.type] = d
    return out


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
