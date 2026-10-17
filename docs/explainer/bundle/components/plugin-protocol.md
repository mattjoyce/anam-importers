---
type: component
title: Plugin protocol (anam_importer.ductile)
description: Reads one JSON request on stdin, runs the named command's handler, and always writes exactly one JSON response on stdout, turning every failure into a structured error with a retry flag.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/ductile.py#run
anchor: "def run(handlers: Dict[str, Handler]) -> None:"
basis: code
tier: supporting
group: shared
depends_on:
  - /components/anam-client.md
---

A plugin is a map from command name to handler, passed to `run`. `ok`, `error` and `event` build the response and its events, and `payload_of` returns the triggering event's payload for `handle`.

`Failure(message, retry)` is the exception a handler raises when its source fails, and the retry flag tells the supervisor whether another try can help. An `AnamError` is handled the same way. Any other exception is reported as not worth retrying, because a plugin that dies with a traceback tells the supervisor nothing it can act on. Bad JSON, a request that is not an object, and an unknown command each get an error response too. `event` takes an optional `dedupe_key`, which the gateway uses to drop a repeat within its window.
