"""Naming a point, through OpenStreetMap Nominatim and a cache on disk.

Nominatim's public endpoint authenticates by a contact User-Agent, not a token, and
asks for at most one request a second. So this keeps a limiter, and a cache keyed by a
grid cell, so a stay re-emitted as it grows, and a second stay at the same spot, make
no new call. A call that cannot be made is not an error here: it returns None, and the
stay is recorded without a place until a later run names it (the geocoder is outside
the error kernel).

The client follows no redirect and bounds the answer: a public endpoint should not be
able to send the run somewhere else or hand it an unbounded body.
"""

from __future__ import annotations

import http.client
import json
import ssl
import time
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

# MAX_RESPONSE bounds one geocoder answer. A reverse lookup is a few kilobytes.
MAX_RESPONSE = 1 << 20

# CELL_DP rounds the centroid to a grid cell for the cache key, ~11 m at 4 places.
# That is finer than any stay radius, so it never joins two places; it only groups a
# stay's own re-queries as its centroid shifts. A store-internal tuning (anam card
# 151): it changes how many calls are made, no result and no limit a person meets.
CELL_DP = 4


class Nominatim:
    """A reverse-geocoding client for one endpoint, rate-limited per OSM policy."""

    def __init__(self, endpoint: str, user_agent: str, rate_limit_seconds: float, timeout: float = 10.0):
        parts = urllib.parse.urlsplit(endpoint)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"geocode endpoint {endpoint!r}: want http:// or https:// and a host")
        self._scheme, self._host, self._port = parts.scheme, parts.hostname, parts.port
        self._path = parts.path or "/reverse"
        self.user_agent = user_agent
        self.rate_limit_seconds = max(0.0, rate_limit_seconds)
        self.timeout = timeout
        self._last = 0.0

    def reverse(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        """The geocoder's answer for a point, or None if the call could not be made or
        said nothing. Never raises: a geocoder that is down must not stop a stay."""
        self._wait()
        query = urllib.parse.urlencode({"format": "jsonv2", "lat": f"{lat:.6f}", "lon": f"{lon:.6f}",
                                        "zoom": "18", "addressdetails": "1"})
        if self._scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                self._host, self._port, timeout=self.timeout, context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=self.timeout)
        try:
            conn.request("GET", f"{self._path}?{query}", headers={"User-Agent": self.user_agent})
            resp = conn.getresponse()
            if resp.status != 200:
                resp.read(MAX_RESPONSE)
                return None
            raw = resp.read(MAX_RESPONSE + 1)
            if len(raw) > MAX_RESPONSE:
                return None
            data = json.loads(raw)
            return data if isinstance(data, dict) and data.get("address") else None
        except (OSError, http.client.HTTPException, ValueError):
            return None
        finally:
            conn.close()

    def _wait(self) -> None:
        if self.rate_limit_seconds:
            elapsed = time.monotonic() - self._last
            if elapsed < self.rate_limit_seconds:
                time.sleep(self.rate_limit_seconds - elapsed)
        self._last = time.monotonic()


# NAME_LADDER is the address keys that make a readable name, most specific first within
# each rank; the first present in each rank is taken. The ranks give locality, then
# city, then state, then country.
NAME_LADDER = (("suburb", "village", "hamlet", "town", "neighbourhood"),
               ("city", "county"),
               ("state",),
               ("country",))


def name_from(data: Dict[str, Any]) -> Optional[str]:
    """A readable location name from a geocoder answer, or its display_name, or None."""
    address = data.get("address") if isinstance(data.get("address"), dict) else {}
    parts = []
    for rank in NAME_LADDER:
        for key in rank:
            value = address.get(key)
            if isinstance(value, str) and value and value not in parts:
                parts.append(value)
                break
    if parts:
        return ", ".join(parts)
    display = data.get("display_name")
    return display if isinstance(display, str) and display else None


def place_from(data: Dict[str, Any], geocoded_at: str, geocoder: str = "nominatim") -> Optional[Dict[str, Any]]:
    """The place object for the Definition from a geocoder answer, or None if it could
    not be named. geocoded_at says how current the name is."""
    name = name_from(data)
    if not name:
        return None
    place: Dict[str, Any] = {"name": name, "geocoder": geocoder, "geocoded_at": geocoded_at}
    if isinstance(data.get("display_name"), str) and data["display_name"]:
        place["display_name"] = data["display_name"]
    if isinstance(data.get("osm_type"), str) and data["osm_type"]:
        place["osm_type"] = data["osm_type"]
    osm_id = data.get("osm_id")
    if isinstance(osm_id, int) and not isinstance(osm_id, bool):
        place["osm_id"] = osm_id
    if isinstance(data.get("address"), dict) and data["address"]:
        place["address"] = {k: v for k, v in data["address"].items() if isinstance(v, (str, int, float))}
    return place


class Cache:
    """Geocoder answers kept on disk by grid cell, so a cell is named once. A read or a
    write that fails is not an error: the worst a broken cache does is a repeat call."""

    def __init__(self, root: Path):
        self.root = root
        self.calls = 0

    def _path(self, lat: float, lon: float) -> Path:
        return self.root / f"{round(lat, CELL_DP):.{CELL_DP}f},{round(lon, CELL_DP):.{CELL_DP}f}.json"

    def get(self, lat: float, lon: float) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self._path(lat, lon).read_text())
        except (OSError, ValueError):
            return None

    def put(self, lat: float, lon: float, data: Dict[str, Any]) -> None:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            self._path(lat, lon).write_text(json.dumps(data, separators=(",", ":")))
        except OSError:
            pass


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def geocoder(nominatim: Nominatim, cache: Cache) -> Callable[[float, float], Optional[Dict[str, Any]]]:
    """A function that returns a cell's geocoder answer, from the cache or one call, as
    {"data": <answer>, "at": <instant it was fetched>}. A named cell is cached, so its
    fetch time is kept honest across re-emits; an unnamed one is not cached, so it is
    tried again next run."""

    def lookup(lat: float, lon: float) -> Optional[Dict[str, Any]]:
        cached = cache.get(lat, lon)
        if isinstance(cached, dict) and isinstance(cached.get("data"), dict):
            return cached
        cache.calls += 1
        data = nominatim.reverse(lat, lon)
        if data is None:
            return None
        entry = {"data": data, "at": _now()}
        cache.put(lat, lon, entry)
        return entry

    return lookup
