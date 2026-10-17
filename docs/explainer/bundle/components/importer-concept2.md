---
type: component
title: anam_concept2
description: Reads workouts from the Concept2 Logbook API into a local cache with fetch, then shapes the cache into exercise.session with handle and poll, which never touch the network.
timestamp: 2026-10-17T00:00:00Z
resource: concept2/run.py#fetch
anchor: "def fetch(request: Dict[str, Any]) -> Dict[str, Any]:"
basis: code
tier: supporting
group: importers
depends_on:
  - /components/envelopes.md
  - /components/definitions.md
  - /components/config-helpers.md
  - /components/plugin-protocol.md
---

Source `concept2`, type `exercise.session` v5 (the same body Garmin carries), identity `/id` as `concept2:session:<result id>`. Each payload holds the IEEE 1752 style body, with splits or intervals and every stroke beside it.

`fetch` is the only command with a network call and the only one that takes a secret, a personal Logbook token named by `token_secret`. The `Logbook` class mirrors the Anam client's rules, a total deadline, a response cap, redirects refused so the token stays home, and 429 and 5xx retryable. It lists results page by page (250 at most), fetches strokes for a result when the listing says it has them, and writes each new or changed result to `cache_dir/<id>.json` atomically. A result the Logbook no longer lists is deleted from the cache, so a later snapshot cannot carry it. See [fetch and shape stay separate](/decisions/fetch-and-shape-are-separate-commands.md).

The start is the monitor's end time (`date_utc`) minus the duration. A result typed in on the Logbook's website has no `date_utc`, so it starts at midnight in the Definition's zone and `start_time_known` is false. Keys include `logbook_url`, `logbook_user`, `timeout`, `lookback_days` and `max_response_bytes`.
