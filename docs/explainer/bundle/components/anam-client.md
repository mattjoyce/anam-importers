---
type: component
title: Anam client (anam_importer.client)
description: A standard-library HTTP client for the five Anam calls an importer makes, with a total deadline, a response cap, no redirects, and a rule that only a whole admission receipt counts as success.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/client.py#Client
anchor: "class Client:"
basis: code
tier: core
group: shared
depends_on: []
---

| Method | Call | Notes |
|---|---|---|
| `definition(type, version)` | `GET /v1/definitions/<type>/<version>` | 404 returns None |
| `definitions()` | `GET /v1/definitions` | each entry needs a string `type` and an integer `current` |
| `register(manifest)` | `POST /v1/definitions` | 200 and 201 both succeed |
| `submit(envelopes, snapshot)` | `POST /v1/envelopes` | 200 must pass `admission`; a 422 with `refused` raises `Refused` |
| `store_document(name, data)` | `POST /v1/documents?ext=` | extension only, left off when not letters and digits or over 16 |
| `snapshot(id)` | `GET /v1/snapshots/<id>` | needs a boolean `complete` |

`_call` opens one connection per request over `http.client`, sets a bearer token and an `Anam-Timeout` header, and keeps one deadline across connect, headers and body. A 3xx is an error, never followed. An answer over `max_response` bytes is a retryable error. `AnamError.retry` is true for 5xx, 429 and transport failures, and false for other 4xx. See [the client trusts only a whole receipt](/decisions/the-client-trusts-only-a-whole-receipt.md) and [no redirect is followed](/invariants/no-redirect-is-followed.md).
