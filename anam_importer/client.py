"""The Anam service, as an importer sees it: publish Definitions, submit batches.

Every call has a total deadline and fails fast. An error says whether trying again
later can help (`retry`), which is what a ductile plugin reports to its supervisor.
A call goes to the configured origin and nowhere else: a redirect is an error, so the
token never reaches another host, port or scheme.
"""

from __future__ import annotations

import http.client
import json
import socket
import ssl
import time
import urllib.parse
from typing import Any, Dict, List, Optional, Tuple

# MAX_RESPONSE bounds what one answer may hold. The largest Anam sends an importer is
# a snapshot report of 1,000 absent ids, well under a megabyte.
MAX_RESPONSE = 8 << 20

# OUTCOMES are what the gate may say became of an envelope.
OUTCOMES = {"admitted", "superseded", "no-op", "tombstoned"}


class AnamError(Exception):
    """A call that did not do what was asked. retry says whether a later try can."""

    def __init__(self, message: str, retry: bool, status: Optional[int] = None):
        super().__init__(message)
        self.retry = retry
        self.status = status


class Refused(AnamError):
    """A batch the gate refused whole. refused names every envelope and why."""

    def __init__(self, message: str, refused: List[Dict[str, Any]]):
        super().__init__(message, retry=False, status=422)
        self.refused = refused


class Client:
    """Calls one Anam daemon under one importer's token."""

    def __init__(self, url: str, token: str, timeout: float = 30.0):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError(f"anam url {url!r}: want http:// or https:// and a host")
        if parts.query or parts.fragment or parts.username:
            raise ValueError(f"anam url {url!r}: want no query, fragment or credentials")
        if not token:
            raise ValueError("an importer's token is required")
        if timeout <= 0:
            raise ValueError(f"timeout {timeout}: want more than 0")
        self.url = url.rstrip("/")
        self._scheme, self._host, self._port = parts.scheme, parts.hostname, parts.port
        self._base = parts.path.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Optional[bytes] = None) -> Tuple[int, Any]:
        """One request to the configured origin, within self.timeout in all: connect,
        headers and body. Its status, and its body as JSON, or NOT_JSON."""
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
        headers = {"Authorization": "Bearer " + self.token,
                   "Anam-Timeout": f"{max(1, int(self.timeout * 1000))}ms"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            conn.request(method, self._base + path, body=body, headers=headers)
            sock = conn.sock  # the response reads it; conn lets go of it on a closing answer
            sock.settimeout(remaining())
            resp = conn.getresponse()
            if 300 <= resp.status < 400:
                # Following it would carry the token to wherever it points.
                raise AnamError(f"{method} {path}: {resp.status} redirect to {resp.getheader('Location')!r} "
                                "not followed; set anam_url to the daemon itself", retry=False, status=resp.status)
            chunks: List[bytes] = []
            size = 0
            while not resp.isclosed():  # it closes itself once Content-Length is read
                sock.settimeout(remaining())
                chunk = resp.read1(65536)
                if not chunk:
                    if resp.length:  # the connection closed short of Content-Length
                        raise http.client.IncompleteRead(b"".join(chunks), resp.length)
                    break
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise AnamError(f"{method} {path}: answer larger than {MAX_RESPONSE} bytes", retry=True)
                chunks.append(chunk)
            return resp.status, _decode(b"".join(chunks))
        except AnamError:
            raise
        except (http.client.HTTPException, TimeoutError, OSError) as exc:
            # The batch may or may not have been written: a resend is how that is
            # settled, since commit is idempotent.
            raise AnamError(f"{method} {path}: {type(exc).__name__}: {exc}", retry=True) from exc
        finally:
            conn.close()

    def definition(self, facet_type: str, version: int) -> Optional[Dict[str, Any]]:
        """The published manifest of facet_type at version, or None if not held."""
        path = f"/v1/definitions/{urllib.parse.quote(facet_type)}/{int(version)}"
        status, body = self._call("GET", path)
        if status == 404:
            return None
        if status != 200:
            raise _error("GET " + path, status, body)
        return _object("GET " + path, body)

    def definitions(self) -> List[Dict[str, Any]]:
        """Every type Anam admits: its origin, current version and versions held."""
        status, body = self._call("GET", "/v1/definitions")
        if status != 200:
            raise _error("GET /v1/definitions", status, body)
        listed = _object("GET /v1/definitions", body).get("definitions")
        if not isinstance(listed, list) or not all(
                isinstance(d, dict) and isinstance(d.get("type"), str) and isinstance(d.get("current"), int)
                for d in listed):
            raise _malformed("GET /v1/definitions", body)
        return listed

    def register(self, manifest: bytes) -> Dict[str, Any]:
        """Register a Definition. 201 and 200 both mean it is now registered."""
        status, body = self._call("POST", "/v1/definitions", manifest)
        if status not in (200, 201):
            raise _error("POST /v1/definitions", status, body)
        return _object("POST /v1/definitions", body)

    def submit(self, envelopes: List[Dict[str, Any]], snapshot: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Submit one batch, as one part of snapshot when given. It is admitted whole,
        or Refused is raised and nothing was written."""
        body: Dict[str, Any] = {"envelopes": envelopes}
        if snapshot:
            body["snapshot"] = snapshot
        payload = json.dumps(body, separators=(",", ":")).encode()
        status, body = self._call("POST", "/v1/envelopes", payload)
        if status == 200:
            return admission(body, len(envelopes))
        if status == 422 and isinstance(body, dict) and isinstance(body.get("refused"), list):
            raise Refused(str(body.get("error", "batch refused")), list(body.get("refused", [])))
        raise _error("POST /v1/envelopes", status, body)

    def snapshot(self, snapshot_id: str) -> Dict[str, Any]:
        """What Anam knows of one of this importer's snapshots: complete, and once it
        is, live, absent and absent_ids."""
        path = "/v1/snapshots/" + urllib.parse.quote(snapshot_id, safe="")
        status, body = self._call("GET", path)
        if status != 200:
            raise _error("GET " + path, status, body)
        report = _object("GET " + path, body)
        if not isinstance(report.get("complete"), bool):
            raise _malformed("GET " + path, body)
        return report


def admission(body: Any, sent: int) -> Dict[str, Any]:
    """body, once it is shown to be the gate's receipt for a batch of sent envelopes:
    W, the change count, and one known outcome for each index. Anything less is not
    evidence that the batch was admitted, so it is an error worth retrying."""
    what = "POST /v1/envelopes"
    a = _object(what, body)
    results = a.get("results")
    if not (isinstance(a.get("w"), int) and not isinstance(a.get("w"), bool) and a["w"] > 0
            and isinstance(a.get("changed"), int) and isinstance(results, list) and len(results) == sent):
        raise _malformed(what, body)
    indexes = set()
    for r in results:
        if not (isinstance(r, dict) and r.get("outcome") in OUTCOMES and isinstance(r.get("index"), int)
                and 0 <= r["index"] < sent):
            raise _malformed(what, body)
        indexes.add(r["index"])
    changed = sum(1 for r in results if r["outcome"] in ("admitted", "superseded"))
    if len(indexes) != sent or a["changed"] != changed:
        raise _malformed(what, body)
    return a


class _NotJSON(str):
    """An answer body that is not JSON, kept as text for the error."""


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw) if raw else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _NotJSON(raw.decode("utf-8", "replace")[:500])


def _object(what: str, body: Any) -> Dict[str, Any]:
    if not isinstance(body, dict):
        raise _malformed(what, body)
    return body


def _malformed(what: str, body: Any) -> AnamError:
    # A 200 that does not say what it should is a proxy, a wrong endpoint or a
    # damaged answer: not evidence of anything, and a later try may reach Anam.
    return AnamError(f"{what}: 200 but not Anam's answer: {str(body)[:200]}", retry=True)


def _error(what: str, status: int, body: Any) -> AnamError:
    msg = body.get("error") if isinstance(body, dict) else None
    # 503 is a write holding the ledger, 504 a deadline, 5xx the daemon: all pass.
    # 4xx is this importer or its data, and repeats until something changes.
    retry = status >= 500 or status == 429
    return AnamError(f"{what}: {status}: {msg or body}", retry=retry, status=status)
