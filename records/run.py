#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["pyyaml>=6"]
# ///
"""anam_records: shapes records files into envelopes for Anam, one batch event at a
time. It is Anam's built-in records worker (internal/capture/records), moved, so the
same record from either path is the same facet with the same payload.

A records file is YAML (or JSON) that a script or an agent wrote from a source
document: a lab report, a hand-kept log, a note made from email.

    document:  {name: ..., sha256: ...}      # the file the records came from
    extracted: {method: ..., version: ...}   # how; a parser, or a model reading
    records:
      - type: lab.result                     # a namespaced facet type
        id: acl:10000001/sodium              # the row's identity, chosen once
        ...fields                            # the payload, verbatim

The payload is the record's fields and nothing else; `type` goes to the envelope.
`document` and `extracted` are the file's provenance, not the fact's. The types are
Anam's bundled Definitions, so this carries none. A records file names no version, so
each batch asks anam_submit to shape its envelopes to the type's current one (as the
worker did), and the gate composes identity and validates.

Commands:
- poll   : every records file under records_dir, in batches, as one snapshot
- handle : on a folder_watch event, the same as poll: a record may move between
           files, so one file alone cannot be checked for duplicates
- health : records_dir is readable and every file in it reads
"""

from __future__ import annotations

import json
import math
import re
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import batches, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402

BATCH_EVENT = "anam_records.batch"

# FIELDS are the keys a records file may hold at its top level, as the worker's
# strict decode allowed them.
FIELDS = ("document", "extracted", "records")

# IDENTITY is the payload fields each type's Definition composes its identity from,
# where that is not the record's id. It is used only to refuse two records claiming
# one identity in a run; the gate composes the identity itself. Identity does not
# include the type, so the check runs across types. Not configurable: it restates
# Anam's bundled Definition, which this importer does not carry or fetch.
IDENTITY = {"health.blood-pressure": ("date_excel", "reading")}

class BadRecords(ductile.Failure):
    """A records file that cannot be used. Retrying will not help."""

    def __init__(self, message: str):
        super().__init__(message, retry=False)


# Scalars are resolved as Go's yaml.v3 resolved them for the worker, not as YAML 1.1
# (PyYAML) would: "yes" is text, "0777" is 511, "1_000" is 1000, and a date is the
# text that was written. A quoted scalar is always text.

_NULLS = {"", "~", "null", "Null", "NULL"}
_BOOLS = {"true": True, "True": True, "TRUE": True, "false": False, "False": False, "FALSE": False}
_SPECIAL_FLOATS = {".nan", ".NaN", ".NAN", ".inf", ".Inf", ".INF", "+.inf", "+.Inf", "+.INF",
                   "-.inf", "-.Inf", "-.INF"}
_YAML_FLOAT = re.compile(r"^[-+]?(\.[0-9]+|[0-9]+(\.[0-9]*)?)([eE][-+]?[0-9]+)?$")
_DOT_FLOAT = re.compile(r"^\.[0-9]+([eE][-+]?[0-9]+)?$")
_INT64 = (-(1 << 63), (1 << 63) - 1)


def _go_int(text: str) -> int | None:
    """text as Go's strconv.ParseInt(text, 0, 64) reads it, or None. Base 0 takes
    0x, 0o and 0b prefixes, and a leading 0 is octal."""
    sign, body = (text[0], text[1:]) if text[:1] in "+-" else ("", text)
    lower = body.lower()
    base, digits = 10, body
    if lower.startswith(("0x", "0o", "0b")):
        base, digits = {"x": 16, "o": 8, "b": 2}[lower[1]], body[2:]
    elif len(body) > 1 and body[0] == "0":
        base, digits = 8, body[1:]
    if not digits or not all(c in "0123456789abcdef"[:base] for c in digits.lower()):
        return None
    value = int(digits, base) * (-1 if sign == "-" else 1)
    return value if _INT64[0] <= value <= _INT64[1] else None


def resolve(text: str) -> Any:
    """A plain scalar's value, as the worker decoded it: bool, None, int, float, or
    the text itself."""
    if text in _NULLS:
        return None
    if text in _BOOLS:
        return _BOOLS[text]
    if text in _SPECIAL_FLOATS:
        raise BadRecords(f"{text} is not a number JSON can carry")
    first = text[0]
    if first == ".":
        return float(text) if _DOT_FLOAT.match(text) else text
    if first in "+-0123456789":
        plain = text.replace("_", "")
        n = _go_int(plain)
        if n is not None:
            return n
        if _YAML_FLOAT.match(plain):
            return float(plain)
    return text


def go_float(f: float) -> str:
    """f as Go's encoding/json writes a float64: shortest digits, plain notation
    between 1e-6 and 1e21, and an exponent without padding outside it."""
    if math.isnan(f) or math.isinf(f):
        raise BadRecords(f"{f} is not a number JSON can carry")
    d = Decimal(repr(f))
    a = abs(f)
    if a != 0 and (a < 1e-6 or a >= 1e21):
        mantissa, exp = f"{d:e}".split("e")
        mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
        sign = "-" if exp.startswith("-") else "+"
        exp = exp.lstrip("+-").lstrip("0") or "0"
        if sign == "+" and len(exp) < 2:
            exp = "0" + exp  # Go pads a positive exponent to two digits
        return f"{mantissa}e{sign}{exp}"
    return format(d.normalize(), "f")


def number(f: float, where: str) -> Any:
    """f as a JSON value whose text is what the worker wrote: an int when Go writes
    no fraction, otherwise the float, provided Python writes it the same way. The
    gate keeps a number's text, so another rendering would supersede the facet."""
    text = go_float(f)
    value: Any = int(text) if re.fullmatch(r"-?[0-9]+", text) else f
    if json.dumps(value) != text:
        raise BadRecords(f"{where}: the number {text} would reach Anam as {json.dumps(value)}")
    return value


def go_text(v: Any) -> str:
    """A scalar id as the worker rendered it, with fmt.Sprint."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e21:
            return str(int(v))
        return repr(v)
    return str(v)


def _loader() -> Any:
    """A YAML loader that composes nodes and resolves nothing, so each scalar keeps
    its text and its style for resolve to read."""
    import yaml

    class Loader(yaml.SafeLoader):
        pass

    Loader.yaml_implicit_resolvers = {}
    return Loader


def plain(node: Any, where: str) -> Any:
    """A composed node as plain values, the way the worker's plain() made them."""
    import yaml

    if isinstance(node, yaml.MappingNode):
        out: Dict[str, Any] = {}
        for k, v in node.value:
            if not isinstance(k, yaml.ScalarNode):
                raise BadRecords(f"{where}: a mapping key is not text")
            if k.value in out:
                raise BadRecords(f"{where}: the key {k.value!r} appears twice")
            out[k.value] = plain(v, where)
        return out
    if isinstance(node, yaml.SequenceNode):
        return [plain(c, where) for c in node.value]
    if node.tag != "tag:yaml.org,2002:str":
        raise BadRecords(f"{where}: the explicit tag {node.tag} is not read")
    if node.style is not None:
        return node.value  # quoted or block: text, always
    v = resolve(node.value)
    return number(v, where) if isinstance(v, float) else v


def records_file(path: Path) -> List[Dict[str, Any]]:
    """The records path holds, each a plain mapping, in file order."""
    import yaml

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ductile.Failure(f"records file {path}: {exc}", retry=True) from exc
    try:
        root = yaml.compose(text, Loader=_loader())
    except yaml.YAMLError as exc:
        raise BadRecords(f"{path}: {exc}") from exc
    if not isinstance(root, yaml.MappingNode):
        raise BadRecords(f"{path}: not a mapping of {', '.join(FIELDS)}")
    top: Dict[str, Any] = {}
    for k, v in root.value:
        if k.value not in FIELDS:
            raise BadRecords(f"{path}: field {k.value!r} is not one of {', '.join(FIELDS)}")
        if k.value in top:
            raise BadRecords(f"{path}: the field {k.value!r} appears twice")
        top[k.value] = v
    recs = top.get("records")
    if not isinstance(recs, yaml.SequenceNode) or not recs.value:
        raise BadRecords(f"{path} declares no records")
    out = []
    for i, node in enumerate(recs.value, start=1):
        rec = plain(node, f"{path} record {i}")
        if not isinstance(rec, dict):
            raise BadRecords(f"{path} record {i}: not a mapping")
        out.append(rec)
    return out


def envelope(rec: Dict[str, Any], person: str, where: str) -> Dict[str, Any]:
    """One record as an envelope shaped to its type's current version."""
    typ = rec.get("type")
    if not isinstance(typ, str) or not typ:
        raise BadRecords(f"{where}: type is required")
    rid = rec.get("id")
    if isinstance(rid, (dict, list)) or rid is None or rid == "":
        raise BadRecords(f"{where}: id is required and must be a scalar")
    payload = {k: v for k, v in rec.items() if k != "type"}
    # The id is text however it was typed: identity is compared as a string.
    payload["id"] = go_text(rid)
    env: Dict[str, Any] = {"type": typ, "payload": payload}
    if person:
        env["asserted_person"] = person
    return env


def identity(env: Dict[str, Any]) -> Tuple[str, ...]:
    """The values the gate composes this envelope's identity from, as text."""
    fields = IDENTITY.get(env["type"], ("id",))
    return tuple(go_text(env["payload"].get(f)) for f in fields)


def files(config: Dict[str, Any]) -> List[Path]:
    """The .yaml, .yml and .json files directly under records_dir, by name. A folder
    with none is a state, nothing extracted yet, not a fault. The suffixes are not
    configurable: they are what the worker read, and a snapshot is that set."""
    root = Path(str(config.get("records_dir", ""))).expanduser()
    if not root.is_dir():
        raise ductile.Failure(f"no records_dir at {root}", retry=False)
    return sorted((p for p in root.iterdir() if p.is_file() and p.suffix.lower() in (".yaml", ".yml", ".json")),
                  key=lambda p: str(p))


def scan(config: Dict[str, Any], person: str) -> Tuple[List[Path], List[Dict[str, Any]]]:
    """Every envelope under records_dir, in file then record order. All of it is
    read before anything is sent, and two records claiming one identity is an error
    in the files, not a supersession."""
    paths = files(config)
    out: List[Dict[str, Any]] = []
    seen: Dict[Tuple[str, ...], str] = {}
    for path in paths:
        for i, rec in enumerate(records_file(path), start=1):
            where = f"{path.name} record {i}"
            env = envelope(rec, person, where)
            key = identity(env)
            if key in seen:
                raise BadRecords(f"{seen[key]} and {where} both declare the row {'/'.join(key)}")
            seen[key] = where
            out.append(env)
    return paths, out


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    paths, envs = scan(config, str(config["person_id"]))
    groups = list(batches(envs))
    events = [ductile.event(BATCH_EVENT, {"envelopes": g, "definitions": [], "current_versions": True, "batch": f"records {i + 1}/{len(groups)}"})
              for i, g in enumerate(groups)]
    # Every records file together is everything written down, so the run is a
    # snapshot of the types it carries.
    if events:
        for ev, part in zip(events, snapshot_parts(len(events), [e["type"] for e in envs])):
            ev["payload"]["snapshot"] = part
    return ductile.ok(f"{len(envs)} record(s) of {len(paths)} file(s) in {len(events)} batch(es)", events=events)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    return poll(request)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    paths, envs = scan(config, "health-check")
    types = sorted({e["type"] for e in envs})
    return ductile.ok(f"{len(envs)} record(s) in {len(paths)} file(s), of {len(types)} type(s)")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
