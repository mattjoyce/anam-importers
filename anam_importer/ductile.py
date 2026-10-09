"""The ductile plugin protocol, version 2: one JSON request on stdin, one JSON
response on stdout, then exit. A plugin is a map of command name to handler; a
handler takes the request and returns a response built with ok() or error().
"""

from __future__ import annotations

import json
import sys
from typing import Any, Callable, Dict, List, Optional

from .client import AnamError

Handler = Callable[[Dict[str, Any]], Dict[str, Any]]


class Failure(Exception):
    """A command that cannot do its work, and whether a later try can. Raise it from
    a handler where a source fails: a locked database passes, a missing table does not."""

    def __init__(self, message: str, retry: bool):
        super().__init__(message)
        self.retry = retry


def ok(result: str, events: Optional[List[Dict[str, Any]]] = None, logs: Optional[List[str]] = None) -> Dict[str, Any]:
    """A command that did what it was asked."""
    return {"status": "ok", "result": result, "events": events or [], "logs": _logs(logs)}


def error(message: str, retry: bool, logs: Optional[List[str]] = None) -> Dict[str, Any]:
    """A command that did not. retry tells the supervisor whether a later try can help."""
    return {"status": "error", "error": message, "retry": retry, "logs": _logs(logs)}


def event(event_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """An event for the core to route."""
    return {"type": event_type, "payload": payload}


def payload_of(request: Dict[str, Any]) -> Dict[str, Any]:
    """The triggering event's payload, for handle; {} for any other command."""
    ev = request.get("event")
    if not isinstance(ev, dict):
        return {}
    payload = ev.get("payload")
    return payload if isinstance(payload, dict) else {}


def _logs(lines: Optional[List[str]]) -> List[Dict[str, str]]:
    return [{"level": "info", "message": line} for line in lines or []]


def run(handlers: Dict[str, Handler]) -> None:
    """Read the request, run its command's handler, write the response.

    An AnamError or a Failure becomes an error carrying its retry. Any other exception
    is a bug or bad config, reported as not worth retrying. Whatever happens, stdout
    holds one response: a plugin that dies with a traceback tells the supervisor
    nothing it can act on.
    """
    try:
        request = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        json.dump(error(f"invalid request JSON: {exc}", retry=False), sys.stdout)
        return
    command = str(request.get("command", "")).strip().lower()
    handler = handlers.get(command)
    if handler is None:
        json.dump(error(f"unknown command {command!r}", retry=False), sys.stdout)
        return
    try:
        response = handler(request)
    except (AnamError, Failure) as exc:
        response = error(str(exc), retry=exc.retry)
    except Exception as exc:  # noqa: BLE001 (the protocol needs an answer for every failure)
        response = error(f"{type(exc).__name__}: {exc}", retry=False)
    json.dump(response, sys.stdout)
