#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["jsonschema>=4.18"]
# ///
"""anam_concept2: shapes the workouts the Concept2 Logbook holds into Anam envelopes,
one activity.exercise-session.concept2 each, one batch event at a time.

ErgData syncs each workout the monitor records to the Logbook, and the Logbook's API
is where it can be read back whole: the result, its splits or intervals, and every
stroke. A result entered by hand on the Logbook's website is there too, with totals
only. Two concerns, kept apart as two commands. `fetch` is the source's reader: it
lists the user's results under a personal token and keeps each one that is new or
changed as a JSON file under cache_dir, strokes included, the way the garmin importer
reads the files GarminDB downloaded. `handle` and `poll` shape what the cache holds
and never touch the network. The importer keeps no state of its own: the cache is
the source's, and Anam makes a resend a no-op.

Commands:
- fetch  : bring the cache up to date with the Logbook
- handle : after a fetch, the results cached in the last lookback_days
- poll   : everything cached, in batches: the resend-everything mode
- health : the cache is readable and everything in it conforms
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import ssl
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from anam_importer import batches, check, envelope, load, snapshot_parts  # noqa: E402
from anam_importer import config as cfg  # noqa: E402
from anam_importer import ductile  # noqa: E402

SESSION_TYPE = "activity.exercise-session.concept2"
BATCH_EVENT = "anam_concept2.batch"
FETCHED_EVENT = "anam_concept2.fetched"

# The DEFAULT_ values are what a key left out of config means: logbook_url,
# logbook_user, timeout (a call's total seconds), lookback_days and
# max_response_bytes.
DEFAULT_URL = "https://log.concept2.com"
# DEFAULT_USER is the Logbook's name for the token's own user.
DEFAULT_USER = "me"
DEFAULT_TIMEOUT = 30.0
# DEFAULT_LOOKBACK_DAYS bounds handle to the files a fetch can have written.
DEFAULT_LOOKBACK_DAYS = 3
# DEFAULT_MAX_RESPONSE bounds one answer: a page of 250 results is under a
# megabyte, a workout's strokes a few tens of kilobytes.
DEFAULT_MAX_RESPONSE = 8 << 20

# PAGE is the most results the Logbook lists per page. Not configurable: it is the
# API's own maximum, and a smaller page is only more calls.
PAGE = 250
# ACCEPT pins the Logbook API's version, as its documentation asks. Not
# configurable: another version is another body, which session() does not read.
ACCEPT = "application/vnd.c2logbook.v1+json"
# READ_CHUNK is how much of an answer one read asks for. Not configurable: it sets
# no limit, since the deadline and max_response bound the read whatever it is.
READ_CHUNK = 65536
# ERROR_EXCERPT bounds how much of a refusal's body an error quotes. Not
# configurable: it shapes a message, not what the importer does.
ERROR_EXCERPT = 200


class Settings(NamedTuple):
    """This run's config, read and checked once, at the start of a command."""

    logbook_url: str
    logbook_user: str
    timeout: float
    lookback_days: float
    max_response: int


def settings(config: Dict[str, Any]) -> Settings:
    return Settings(
        logbook_url=cfg.url(config, "logbook_url", DEFAULT_URL),
        logbook_user=cfg.text(config, "logbook_user", DEFAULT_USER),
        timeout=cfg.number(config, "timeout", DEFAULT_TIMEOUT, 0, 3600, low_open=True),
        lookback_days=cfg.number(config, "lookback_days", DEFAULT_LOOKBACK_DAYS, 0, 3650, low_open=True),
        max_response=cfg.integer(config, "max_response_bytes", DEFAULT_MAX_RESPONSE, 1, 1 << 30),
    )

# ZONE is where a result entered on the web, which names a day and no zone, is
# placed. The Definition says so, in its fact_time; it is read from there so it is
# stated once.
ZONE = ZoneInfo(json.loads((HERE / "definitions" / f"{SESSION_TYPE}.json").read_text())["meta"]["time_semantics"]["fact_time"]["zone"])

# ERG_NAMES maps the Logbook's result type to the Definition's activity name,
# Google Fit's vocabulary. An erg not here is "other"; erg_type keeps the Logbook's
# word either way. Not configurable: it is what the payload means.
ERG_NAMES = {"rower": "rowing.machine", "bike": "biking.stationary", "water": "rowing"}

# HEART_RATES are the Logbook's heart_rate figures a payload keeps, by the
# Definition's name for them. The monitor writes zero for a figure it has no belt
# for, so zero is no figure.
HEART_RATES = {"avg_hr_bpm": "average", "max_hr_bpm": "max", "ending_hr_bpm": "ending"}
SPLIT_HEART_RATES = {**HEART_RATES, "min_hr_bpm": "min", "rest_hr_bpm": "rest"}


def number(v: float) -> Any:
    """v as JSON writes a whole number: 117, not 117.0."""
    return int(v) if float(v).is_integer() else v


def tenths(v: Any) -> Optional[Any]:
    """A figure the Logbook gives in tenths of a second, in seconds; None when it
    gave none."""
    return None if not isinstance(v, (int, float)) or isinstance(v, bool) else number(v / 10)


def figure(v: Any) -> Optional[Any]:
    """A plain number the Logbook wrote, or None when it wrote none."""
    return None if not isinstance(v, (int, float)) or isinstance(v, bool) else number(v)


def positive(v: Any) -> Optional[Any]:
    """A figure the Logbook wrote as more than zero, or None: the monitor's zero
    means no measurement."""
    n = figure(v)
    return n if n is not None and n > 0 else None


def start_of(result: Dict[str, Any], seconds: Any) -> Tuple[str, bool]:
    """When the workout started, and whether the monitor says so. The Logbook's date
    is the monitor's end of workout; date_utc is that instant in UTC, and the start
    is seconds before it. A result entered on the web has no date_utc and a date at
    midnight: its start is that day at midnight in ZONE."""
    utc = result.get("date_utc")
    if isinstance(utc, str) and utc:
        end = datetime.strptime(utc, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        return (end - timedelta(seconds=float(seconds))).strftime("%Y-%m-%dT%H:%M:%SZ"), True
    day = datetime.strptime(str(result["date"]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZONE)
    return day.isoformat(), False


def heart(target: Dict[str, Any], rates: Any, names: Dict[str, str]) -> None:
    """The Logbook's heart_rate object's figures, by the Definition's names, where
    they are more than zero."""
    if not isinstance(rates, dict):
        return
    for key, name in names.items():
        if positive(rates.get(name)) is not None:
            target[key] = positive(rates[name])


def split(i: int, s: Dict[str, Any]) -> Dict[str, Any]:
    """One of the Logbook's splits or intervals as a Definition split."""
    p: Dict[str, Any] = {"position": i + 1, "duration_sec": tenths(s.get("time"))}
    for key, name in (("distance_m", "distance"), ("kcal", "calories_total"),
                      ("watt_minutes", "wattminutes_total"), ("avg_spm", "stroke_rate")):
        if figure(s.get(name)) is not None:
            p[key] = figure(s[name])
    if tenths(s.get("rest_time")) is not None:
        p["rest_time_sec"] = tenths(s["rest_time"])
    heart(p, s.get("heart_rate"), SPLIT_HEART_RATES)
    return p


def stroke(s: Dict[str, Any]) -> Dict[str, Any]:
    """One stroke, the Logbook's units converted: t and p are tenths of a second, d
    decimetres."""
    p: Dict[str, Any] = {"time_sec": tenths(s.get("t")), "distance_m": tenths(s.get("d"))}
    if tenths(s.get("p")) is not None:
        p["pace_500m_sec"] = tenths(s["p"])
    if figure(s.get("spm")) is not None:
        p["spm"] = figure(s["spm"])
    if positive(s.get("hr")) is not None:
        p["hr_bpm"] = positive(s["hr"])
    return p


def session(cached: Dict[str, Any]) -> Dict[str, Any]:
    """One cached result, {"result": ..., "strokes": [...]}, as an activity.exercise-session.concept2
    payload. A figure the Logbook did not give is left out."""
    r = cached["result"]
    seconds = tenths(r.get("time"))
    if seconds is None:
        raise ValueError(f"result {r.get('id')}: no time")
    start, known = start_of(r, seconds)
    p: Dict[str, Any] = {
        "id": f"concept2:session:{int(r['id'])}",
        "activity_name": ERG_NAMES.get(str(r.get("type")), "other"),
        "effective_time_frame": {"time_interval": {"start_date_time": start, "duration": {"value": seconds, "unit": "sec"}}},
        "duration": {"value": seconds, "unit": "sec"},
        "source": "Concept2 Logbook",
        "start_time_known": known,
    }
    if positive(r.get("distance")) is not None:
        p["distance"] = {"value": positive(r["distance"]), "unit": "m"}
    for key, name, unit in (("kcal_burned", "calories_total", "kcal"), ("base_movement_quantity", "stroke_count", "strokes"),
                            ("average_cadence", "stroke_rate", "strokes/min")):
        if figure(r.get(name)) is not None:
            p[key] = {"value": figure(r[name]), "unit": unit}
    for key, name in (("drag_factor", "drag_factor"), ("watt_minutes", "wattminutes_total"), ("rest_distance_m", "rest_distance")):
        if figure(r.get(name)) is not None:
            p[key] = figure(r[name])
    if tenths(r.get("rest_time")) is not None:
        p["rest_time_sec"] = tenths(r["rest_time"])
    heart(p, r.get("heart_rate"), HEART_RATES)
    for key, name in (("erg_type", "type"), ("workout_type", "workout_type"), ("logbook_source", "source"),
                      ("logbook_date", "date"), ("logbook_timezone", "timezone"), ("weight_class", "weight_class"),
                      ("comments", "comments")):
        if isinstance(r.get(name), str) and r[name]:
            p[key] = r[name]
    for key in ("verified", "ranked"):
        if isinstance(r.get(key), bool):
            p[key] = r[key]
    workout = r.get("workout") if isinstance(r.get("workout"), dict) else {}
    parts = workout.get("splits") or workout.get("intervals") or []
    if parts:
        p["splits"] = [split(i, s) for i, s in enumerate(parts)]
    strokes = cached.get("strokes") or []
    if strokes:
        p["stroke_series"] = [stroke(s) for s in strokes]
    return p


class Logbook:
    """The Concept2 Logbook API under one personal token. Every call has a total
    deadline and fails fast; a redirect is an error, so the token never reaches
    another host."""

    def __init__(self, url: str, token: str, timeout: float, max_response: int):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ductile.Failure(f"logbook_url {url!r}: want http:// or https:// and a host", retry=False)
        if parts.query or parts.fragment or parts.username:
            raise ductile.Failure(f"logbook_url {url!r}: want no query, fragment or credentials", retry=False)
        if not token:
            raise ductile.Failure("the Logbook token is empty", retry=False)
        self._scheme, self._host, self._port = parts.scheme, parts.hostname, parts.port
        self._base = parts.path.rstrip("/")
        self.token = token
        self.timeout = timeout
        self.max_response = max_response

    def get(self, path: str) -> Any:
        """GET path, its JSON body."""
        deadline = time.monotonic() + self.timeout

        def remaining() -> float:
            left = deadline - time.monotonic()
            if left <= 0:
                raise TimeoutError(f"no answer within {self.timeout}s")
            return left

        if self._scheme == "https":
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                self._host, self._port, timeout=remaining(), context=ssl.create_default_context())
        else:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=remaining())
        headers = {"Authorization": "Bearer " + self.token, "Accept": ACCEPT}
        try:
            conn.request("GET", self._base + path, headers=headers)
            sock = conn.sock
            sock.settimeout(remaining())
            resp = conn.getresponse()
            if 300 <= resp.status < 400:
                raise ductile.Failure(f"GET {path}: {resp.status} redirect not followed; set logbook_url to the API itself",
                                      retry=False)
            chunks: List[bytes] = []
            size = 0
            while not resp.isclosed():
                sock.settimeout(remaining())
                chunk = resp.read1(READ_CHUNK)
                if not chunk:
                    if resp.length:
                        raise http.client.IncompleteRead(b"".join(chunks), resp.length)
                    break
                size += len(chunk)
                if size > self.max_response:
                    raise ductile.Failure(f"GET {path}: answer larger than {self.max_response} bytes", retry=True)
                chunks.append(chunk)
            raw = b"".join(chunks)
        except ductile.Failure:
            raise
        except (http.client.HTTPException, TimeoutError, OSError, socket.error) as exc:
            raise ductile.Failure(f"GET {path}: {type(exc).__name__}: {exc}", retry=True) from exc
        finally:
            conn.close()
        if resp.status != 200:
            # 401 and 403 are the token, 404 the user or result: none changes on its own.
            # 429 and 5xx are the Logbook, and pass.
            retry = resp.status >= 500 or resp.status == 429
            raise ductile.Failure(f"GET {path}: {resp.status}: {raw[:ERROR_EXCERPT].decode('utf-8', 'replace')}", retry=retry)
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ductile.Failure(f"GET {path}: not JSON: {exc}", retry=True) from exc

    def results(self, user: str) -> List[Dict[str, Any]]:
        """Every result the Logbook lists for user, every page."""
        out: List[Dict[str, Any]] = []
        page = 1
        while True:
            body = self.get(f"/api/users/{urllib.parse.quote(user)}/results?number={PAGE}&page={page}")
            data = body.get("data") if isinstance(body, dict) else None
            if not isinstance(data, list):
                raise ductile.Failure("the results listing is not the Logbook's: no data list", retry=True)
            out += [r for r in data if isinstance(r, dict) and isinstance(r.get("id"), int)]
            pages = ((body.get("meta") or {}).get("pagination") or {}).get("total_pages")
            if not isinstance(pages, int) or page >= pages:
                return out
            page += 1

    def strokes(self, user: str, result_id: int) -> List[Dict[str, Any]]:
        body = self.get(f"/api/users/{urllib.parse.quote(user)}/results/{int(result_id)}/strokes")
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise ductile.Failure(f"result {result_id}: the strokes answer is not the Logbook's", retry=True)
        return data


def cache_dir(config: Dict[str, Any]) -> Path:
    root = Path(str(config["cache_dir"]))
    if not root.is_dir():
        raise ductile.Failure(f"no cache_dir at {root}", retry=False)
    return root


def cached_files(root: Path, since: Optional[float] = None) -> List[Path]:
    """The cached results, oldest id first; with since, those written at or after it."""
    files = sorted((p for p in root.glob("*.json") if p.is_file()), key=lambda p: (len(p.stem), p.stem))
    if since is None:
        return files
    try:
        return [p for p in files if p.stat().st_mtime >= since]
    except FileNotFoundError as exc:
        raise ductile.Failure(f"{exc.filename} went while the run read it", retry=True) from exc


def read_cached(path: Path) -> Dict[str, Any]:
    """One cached file. One that is not a cached result is a ValueError."""
    try:
        doc = json.loads(path.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(str(exc)) from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("result"), dict):
        raise ValueError("not a cached result")
    return doc


def write_cached(path: Path, doc: Dict[str, Any]) -> None:
    """doc at path, whole or not at all."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":"), sort_keys=True))
    os.replace(tmp, path)


def fetch(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    root = cache_dir(config)
    name = str(config.get("token_secret", ""))
    token = (request.get("secrets") or {}).get(name, "")
    if not token:
        raise ductile.Failure(f"no secret named {name!r} was handed to fetch", retry=False)
    user = s.logbook_user
    api = Logbook(s.logbook_url, str(token), s.timeout, s.max_response)
    listed = api.results(user)
    fetched: List[int] = []
    for r in listed:
        path = root / f"{r['id']}.json"
        held: Optional[Dict[str, Any]] = None
        if path.is_file():
            try:
                held = read_cached(path)
            except ValueError:
                held = None
        wants_strokes = bool(r.get("stroke_data"))
        if held is not None and held["result"] == r and (not wants_strokes or held.get("strokes")):
            continue
        strokes = api.strokes(user, r["id"]) if wants_strokes else []
        write_cached(path, {"result": r, "strokes": strokes})
        fetched.append(int(r["id"]))
    # A result the Logbook no longer lists was deleted there, and a snapshot must not
    # carry it; the listing was read whole, so the cache can follow it.
    ids = {int(r["id"]) for r in listed}
    removed: List[int] = []
    for path in cached_files(root):
        if path.stem.isdigit() and int(path.stem) not in ids:
            path.unlink()
            removed.append(int(path.stem))
    events = []
    if fetched or removed:
        events.append(ductile.event(FETCHED_EVENT, {"fetched": fetched, "removed": removed}))
    return ductile.ok(f"{len(listed)} result(s) listed, {len(fetched)} fetched, {len(removed)} removed", events=events)


def shape(files: List[Path]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Every cached result in files as a payload, by id, and a log line per file that
    would not read."""
    payloads: List[Dict[str, Any]] = []
    logs: List[str] = []
    for path in files:
        try:
            payloads.append(session(read_cached(path)))
        except FileNotFoundError:
            raise ductile.Failure(f"{path.name} went while the run read it", retry=True) from None
        except (ValueError, KeyError, TypeError) as exc:
            logs.append(f"skipped {path.name}: {exc}")
    return payloads, logs


def batch_events(payloads: List[Dict[str, Any]], person: str, snapshot: bool) -> List[Dict[str, Any]]:
    definition = load(HERE)[SESSION_TYPE]
    envs = [envelope(definition, p, asserted_person=person) for p in payloads]
    check({SESSION_TYPE: definition}, envs)
    groups = list(batches(envs))
    parts = snapshot_parts(len(groups), [SESSION_TYPE]) if snapshot and groups else [None] * len(groups)
    events = []
    for i, (g, part) in enumerate(zip(groups, parts)):
        payload: Dict[str, Any] = {"envelopes": g, "definitions": [definition.body.decode()],
                                   "batch": f"{SESSION_TYPE} {i + 1}/{len(groups)}"}
        if part is not None:
            payload["snapshot"] = part
        events.append(ductile.event(BATCH_EVENT, payload))
    return events


def run_over(config: Dict[str, Any], files: List[Path], snapshot: bool) -> Dict[str, Any]:
    payloads, logs = shape(files)
    # A file that would not read leaves its workout out, so the run is not everything.
    events = batch_events(payloads, str(config["person_id"]), snapshot and not logs)
    return ductile.ok(f"{len(payloads)} workout(s) from {len(files)} cached result(s), {len(events)} batch(es)",
                      events=events, logs=logs)


def handle(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    s = settings(config)
    return run_over(config, cached_files(cache_dir(config), time.time() - s.lookback_days * 86400), snapshot=False)


def poll(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    settings(config)  # every command checks the whole config, so a bad value fails at start
    # The cache follows the Logbook's listing whole, so poll's run is a snapshot,
    # unless a file would not read.
    return run_over(config, cached_files(cache_dir(config)), snapshot=True)


def health(request: Dict[str, Any]) -> Dict[str, Any]:
    config = request.get("config") or {}
    settings(config)  # every command checks the whole config, so a bad value fails at start
    files = cached_files(cache_dir(config))
    payloads, logs = shape(files)
    definition = load(HERE)[SESSION_TYPE]
    check({SESSION_TYPE: definition}, [envelope(definition, p) for p in payloads])
    if logs:
        return ductile.error(f"{len(logs)} of {len(files)} cached result(s) would not read", retry=False, logs=logs)
    return ductile.ok(f"{len(payloads)} {SESSION_TYPE} v{definition.version} from {len(files)} cached result(s), every one conforming")


if __name__ == "__main__":
    ductile.run({"fetch": fetch, "handle": handle, "poll": poll, "health": health})
