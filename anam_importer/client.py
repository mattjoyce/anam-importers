"""The Anam service, as an importer sees it: publish Definitions, submit batches.

Every call has a timeout and fails fast. An error says whether trying again later
can help (`retry`), which is what a ductile plugin reports to its supervisor.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple


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
        if not url.startswith(("http://", "https://")):
            raise ValueError(f"anam url {url!r}: want http:// or https://")
        if not token:
            raise ValueError("an importer's token is required")
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Optional[bytes] = None) -> Tuple[int, Any]:
        req = urllib.request.Request(self.url + path, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        req.add_header("Anam-Timeout", f"{int(self.timeout)}s")
        if body is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310 (url is checked)
                return resp.status, _decode(resp.read())
        except urllib.error.HTTPError as exc:
            return exc.code, _decode(exc.read())
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AnamError(f"{method} {path}: {exc}", retry=True) from exc

    def definition(self, facet_type: str, version: int) -> Optional[Dict[str, Any]]:
        """The published manifest of facet_type at version, or None if not held."""
        path = f"/v1/definitions/{urllib.parse.quote(facet_type)}/{int(version)}"
        status, body = self._call("GET", path)
        if status == 404:
            return None
        if status != 200:
            raise _error("GET " + path, status, body)
        return body

    def definitions(self) -> List[Dict[str, Any]]:
        """Every type Anam admits: its origin, current version and versions held."""
        status, body = self._call("GET", "/v1/definitions")
        if status != 200:
            raise _error("GET /v1/definitions", status, body)
        return list(body.get("definitions", []))

    def register(self, manifest: bytes) -> Dict[str, Any]:
        """Register a Definition. 201 and 200 both mean it is now registered."""
        status, body = self._call("POST", "/v1/definitions", manifest)
        if status not in (200, 201):
            raise _error("POST /v1/definitions", status, body)
        return body

    def submit(self, envelopes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Submit one batch. It is admitted whole, or Refused is raised and nothing
        was written."""
        payload = json.dumps({"envelopes": envelopes}, separators=(",", ":")).encode()
        status, body = self._call("POST", "/v1/envelopes", payload)
        if status == 200:
            return body
        if status == 422 and isinstance(body, dict):
            raise Refused(str(body.get("error", "batch refused")), list(body.get("refused", [])))
        raise _error("POST /v1/envelopes", status, body)


def _decode(raw: bytes) -> Any:
    try:
        return json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return {"error": raw.decode("utf-8", "replace")[:500]}


def _error(what: str, status: int, body: Any) -> AnamError:
    msg = body.get("error") if isinstance(body, dict) else None
    # 503 is a write holding the ledger, 504 a deadline, 5xx the daemon: all pass.
    # 4xx is this importer or its data, and repeats until something changes.
    retry = status >= 500 or status == 429
    return AnamError(f"{what}: {status}: {msg or body}", retry=retry, status=status)
