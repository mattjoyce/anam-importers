#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18"]
# ///
"""anam_stays: names the places a phone stopped, as place.stay facets.

The owntracks plugin spools every fix the phone posted, one JSON line per message,
under <spool_dir>/<device>/<YYYY-MM>.jsonl. This importer reads that same spool, finds
the stays (a run of consecutive fixes that held within radius_m for at least
min_dwell_minutes), and emits one place.stay per stay. It geocodes each stay's
centroid once, through a cache on disk, so re-emits and repeat visits make no new call.

The stay is derived, not the track changed: place.track facets are never touched, so
the raw fix stays raw and recoverable. The geocoder is outside the error kernel: if it
is down a stay is emitted without a place, and the place backfills on a later run.

It holds no Anam token: it emits anam_stays.batch events, at most 49 envelopes to a
batch, for anam_submit to post. Coordinates stay in the payload; logs carry counts only.

Commands:
- handle : after a pull, the stays whose last fix was received in the last lookback_days
- poll   : every stay the spool holds, in batches: the resend-everything mode
- health : the spool is readable and every stay conforms to the Definition
"""

from __future__ import annotations

import json
import math
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import ductile  # noqa: E402
from stays.geocode import Cache, Nominatim, geocoder, place_from  # noqa: E402

STAY_TYPE = "place.stay"
BATCH_EVENT = "anam_stays.batch"

# DEFAULT_LOOKBACK_DAYS bounds handle to the stays a pull can have touched. As with the
# owntracks importer, a phone back from being offline sends its queue now, so an old
# fix received now makes its stay recent.
DEFAULT_LOOKBACK_DAYS = 2

# DEFAULT_RADIUS_M is how far a stay may spread from its anchor and still be one place.
# Significant-change fixes plus GPS noise sit well under this; two readings this far
# apart are the same place for naming.
DEFAULT_RADIUS_M = 100.0

# DEFAULT_MIN_DWELL_MINUTES is the shortest run of fixes that counts as a stay. Less is
# passing through, not stopping, and is left out.
DEFAULT_MIN_DWELL_MINUTES = 10.0

# DEFAULT_RATE_LIMIT_SECONDS honours Nominatim's one-request-a-second policy with a
# margin. A keyed, higher-rate endpoint can set it lower.
DEFAULT_RATE_LIMIT_SECONDS = 1.1

# DEFAULT_GEOCODE_ENDPOINT and DEFAULT_GEOCODE_USER_AGENT are the public OSM Nominatim
# reverse endpoint and a contact User-Agent, which the public endpoint needs in place
# of a token. Point them at a keyed, Nominatim-compatible endpoint to go faster.
DEFAULT_GEOCODE_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
DEFAULT_GEOCODE_USER_AGENT = "anam-stays/0.1 (+https://github.com/mattjoyce/anam-importers)"

# MAX_PAYLOAD is the gate's bound on one payload, less room for the envelope. A stay is
# small, so this only ever guards against a pathological address blob.
MAX_PAYLOAD = 290 * 1024


def instant(tst: int) -> str:
    return datetime.fromtimestamp(tst, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Metres between two WGS-84 points."""
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class Fix:
    """One fix the spool holds, pared to what a stay needs."""

    device: str
    tst: int
    lat: float
    lon: float
    received: int


@dataclass
class Stay:
    """A run of fixes that held within a radius. Its centroid, span and spread."""

    device: str
    fixes: List[Fix]

    @property
    def lat(self) -> float:
        return sum(f.lat for f in self.fixes) / len(self.fixes)

    @property
    def lon(self) -> float:
        return sum(f.lon for f in self.fixes) / len(self.fixes)

    @property
    def start(self) -> str:
        return instant(self.fixes[0].tst)

    @property
    def end(self) -> str:
        return instant(self.fixes[-1].tst)

    @property
    def received(self) -> int:
        return max(f.received for f in self.fixes)

    def radius_m(self) -> float:
        lat, lon = self.lat, self.lon
        return max((haversine(lat, lon, f.lat, f.lon) for f in self.fixes), default=0.0)

    def payload(self, geocode: Callable[[float, float], Optional[Dict[str, Any]]]) -> Dict[str, Any]:
        lat, lon = round(self.lat, 6), round(self.lon, 6)
        p: Dict[str, Any] = {"id": f"stay:{self.device}:{self.start}", "device": self.device,
                             "start": self.start, "end": self.end, "lat": lat, "lon": lon,
                             "fixes": len(self.fixes), "radius_m": round(self.radius_m(), 1),
                             # The start is the first fix's tst, an epoch OwnTracks
                             # writes in UTC by its own definition (anam card 198).
                             "source_time": {"value": str(self.fixes[0].tst), "zone": "UTC", "basis": "source"}}
        entry = geocode(lat, lon)
        if entry is not None:
            place = place_from(entry["data"], entry["at"])
            if place is not None:
                p["place"] = place
        return p


@dataclass
class Read:
    """What a read of the spool found: the fixes per device, and what it could not use."""

    fixes: Dict[str, Dict[int, Fix]] = field(default_factory=dict)
    lines: int = 0
    bad: int = 0

    def logs(self) -> List[str]:
        return [f"skipped {self.bad} spool line(s) that would not read"] if self.bad else []


def spool_dir(config: Dict[str, Any]) -> Path:
    root = Path(str(config["spool_dir"]))
    if not root.is_dir():
        raise ductile.Failure(f"no spool_dir at {root}", retry=False)
    return root


def lines_of(path: Path) -> Iterator[str]:
    """Each complete line of a spool file. A last line without its newline is a pull
    still appending, or torn by a crash the pull repairs: not yet a line."""
    try:
        text = path.read_bytes().decode("utf-8", "replace")
    except FileNotFoundError:
        raise ductile.Failure(f"{path.name} went while the run read it", retry=True) from None
    for line in text.split("\n")[:-1]:
        if line.strip():
            yield line


def read_spool(root: Path) -> Read:
    """Every location fix in the spool, by device and fix time. Rows are taken in the
    receiver's id order, so the first received of a repeated fix time is kept."""
    out = Read()
    rows: List[Tuple[int, str, str]] = []
    for path in sorted(p for p in root.glob("*/*.jsonl") if p.is_file()):
        device = path.parent.name
        for line in lines_of(path):
            out.lines += 1
            try:
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get("id"), int) or not isinstance(row.get("body"), str):
                    raise ValueError
            except ValueError:
                out.bad += 1
                continue
            rows.append((row["id"], device, line))
    rows.sort(key=lambda r: r[0])
    for buffer_id, device, line in rows:
        row = json.loads(line)
        try:
            body = json.loads(row["body"])
        except ValueError:
            out.bad += 1
            continue
        if not isinstance(body, dict) or body.get("_type") != "location":
            continue
        tst, lat, lon = body.get("tst"), body.get("lat"), body.get("lon")
        if not isinstance(tst, int) or isinstance(tst, bool) or tst <= 0:
            continue
        if not _is_number(lat) or not _is_number(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            continue
        received = row.get("received_at")
        by_tst = out.fixes.setdefault(device, {})
        by_tst.setdefault(tst, Fix(device, tst, float(lat), float(lon),
                                   received if isinstance(received, int) and not isinstance(received, bool) else 0))
    return out


def _is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def detect_stays(fixes: List[Fix], radius_m: float, min_dwell_s: float) -> List[Stay]:
    """The stays in one device's fixes, oldest first. A stay is a maximal run of fixes
    that began at an anchor and held within radius_m of it, lasting at least min_dwell_s.
    Fixes between stays are movement and make no stay."""
    ordered = sorted(fixes, key=lambda f: f.tst)
    stays: List[Stay] = []
    i, n = 0, len(ordered)
    while i < n:
        anchor = ordered[i]
        j = i + 1
        while j < n and haversine(anchor.lat, anchor.lon, ordered[j].lat, ordered[j].lon) <= radius_m:
            j += 1
        members = ordered[i:j]
        if members[-1].tst - members[0].tst >= min_dwell_s:
            stays.append(Stay(anchor.device, members))
        i = j if j > i + 1 else i + 1
    return stays


def build_geocoder(config: Dict[str, Any]) -> Callable[[float, float], Optional[Dict[str, Any]]]:
    cache = Cache(Path(str(config["geocache_dir"])))
    nominatim = Nominatim(
        endpoint=str(config.get("geocode_endpoint", DEFAULT_GEOCODE_ENDPOINT)),
        user_agent=str(config.get("geocode_user_agent", DEFAULT_GEOCODE_USER_AGENT)),
        rate_limit_seconds=float(config.get("rate_limit_seconds", DEFAULT_RATE_LIMIT_SECONDS)))
    return geocoder(nominatim, cache)


def all_stays(read: Read, config: Dict[str, Any]) -> List[Stay]:
    radius = float(config.get("radius_m", DEFAULT_RADIUS_M))
    dwell = float(config.get("min_dwell_minutes", DEFAULT_MIN_DWELL_MINUTES)) * 60
    stays: List[Stay] = []
    for device in sorted(read.fixes):
        stays.extend(detect_stays(list(read.fixes[device].values()), radius, dwell))
    return sorted(stays, key=lambda s: (s.start, s.device))


def sized(payloads: List[Dict[str, Any]], logs: List[str]) -> List[Dict[str, Any]]:
    out = []
    for p in payloads:
        if len(json.dumps(p, separators=(",", ":"))) > MAX_PAYLOAD:
            logs.append(f"skipped {p['id']}: over {MAX_PAYLOAD} bytes")
            continue
        out.append(p)
    return out


def batch_events(payloads: List[Dict[str, Any]], person: str, snapshot: bool) -> List[Dict[str, Any]]:
    definitions = load(HERE)
    definition = definitions[STAY_TYPE]
    envs = [envelope(definition, p, asserted_person=person) for p in payloads]
    check(definitions, envs)
    groups = list(batches(envs))
    parts = snapshot_parts(len(groups), [STAY_TYPE]) if snapshot and groups else [None] * len(groups)
    events = []
    for i, (g, part) in enumerate(zip(groups, parts)):
        payload: Dict[str, Any] = {"envelopes": g, "definitions": definitions.manifests(),
                                   "batch": f"{STAY_TYPE} {i + 1}/{len(groups)}"}
        if part is not None:
            payload["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, payload))
    return events


def run_over(config: Dict[str, Any], since: Optional[float]) -> Dict[str, Any]:
    read = read_spool(spool_dir(config))
    stays = all_stays(read, config)
    if since is not None:
        stays = [s for s in stays if s.received >= since]
    logs = read.logs()
    geocode = build_geocoder(config)
    payloads = sized([s.payload(geocode) for s in stays], logs)
    placed = sum(1 for p in payloads if "place" in p)
    # A line that would not read leaves fixes out, so the run is not everything.
    whole = read.bad == 0 and len(payloads) == len(stays)
    events = batch_events(payloads, str(config["person_id"]), since is None and whole)
    return ductile.ok(f"{len(payloads)} stay(s), {placed} named from {read.lines} spool line(s), "
                      f"{len(events)} batch(es)", events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    days = float(config.get("lookback_days", DEFAULT_LOOKBACK_DAYS))
    return run_over(config, time.time() - days * 86400)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    return run_over(config, None)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    read = read_spool(spool_dir(config))
    stays = all_stays(read, config)
    definition = load(HERE)[STAY_TYPE]
    # Name nothing here: conformance is of the stay's shape, which the place only adds to.
    payloads = [s.payload(lambda lat, lon: None) for s in stays]
    check({STAY_TYPE: definition}, [envelope(definition, p) for p in payloads])
    if read.bad:
        return ductile.error(f"{read.bad} spool line(s) would not read", retry=False, logs=read.logs())
    return ductile.ok(f"{len(payloads)} {STAY_TYPE} v{definition.version} stay(s) from {read.lines} spool line(s), "
                      "every one conforming")


if __name__ == "__main__":
    ductile.run({"handle": handle, "poll": poll, "health": health})
