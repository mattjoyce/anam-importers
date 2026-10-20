---
type: workflow
title: Fetch and shape a Concept2 workout
description: The fetch command brings a local cache up to date from the Logbook API, and handle or poll then shape the cached results into activity.exercise-session.concept2 envelopes without touching the network.
timestamp: 2026-10-17T00:00:00Z
resource: concept2/run.py#fetch
anchor: "api = Logbook(s.logbook_url, str(token), s.timeout, s.max_response)"
basis: code
tier: supporting
trigger: A schedule runs fetch, and a pipeline or a schedule runs handle or poll afterwards.
steps:
  - actor: /components/importer-concept2.md
    caller: /components/ductile-gateway.md
    label: read the token from the granted secret
    action: "`fetch` takes the secret named by `token_secret` from the request and fails, not retrying, if it was not handed over. The token is for the Logbook and is never an Anam token."
    reads: [/data-structures/plugin-request.md]
    resource: concept2/run.py#fetch
    anchor: 'token = (request.get("secrets") or {}).get(name, "")'
  - actor: /components/importer-concept2.md
    label: list every result, page by page
    action: "Up to 250 results a page, following the listing's page count. A listing without a data list is a retryable failure."
    resource: concept2/run.py#results
    anchor: "/results?number={PAGE}&page={page}"
  - actor: /components/importer-concept2.md
    label: fetch strokes for new or changed results
    action: "A result already cached with an equal body and its strokes is skipped. Otherwise, when the listing says stroke data exists, the strokes are fetched too."
    resource: concept2/run.py#fetch
    anchor: "strokes = api.strokes(user, r[\"id\"]) if wants_strokes else []"
  - actor: /components/importer-concept2.md
    label: write each cache file whole
    action: "`write_cached` writes a temporary file and renames it over the target, so a crash cannot leave a half-written result."
    writes: [/data-structures/cached-result.md]
    resource: concept2/run.py#write_cached
    anchor: "os.replace(tmp, path)"
  - actor: /components/importer-concept2.md
    label: drop results the Logbook no longer lists
    action: "The listing was read whole, so the cache follows it. A deleted result is removed, and a later snapshot cannot carry it."
    resource: concept2/run.py#fetch
    anchor: "path.unlink()"
  - actor: /components/importer-concept2.md
    label: announce what changed
    action: "If anything was fetched or removed, `fetch` emits `anam_concept2.fetched` with the two id lists. The result line counts results listed, fetched and removed."
    writes: [/data-structures/plugin-response.md]
    resource: concept2/run.py#fetch
    anchor: "events.append(ductile.event(FETCHED_EVENT"
  - actor: /components/importer-concept2.md
    label: shape each cached result
    action: "`handle` reads the cache files modified within `lookback_days`, `poll` all of them. `session` derives the start from `date_utc` minus the duration, converts the Logbook's tenths of a second to seconds, and drops the monitor's zero heart rates as no figure."
    reads: [/data-structures/cached-result.md]
    resource: concept2/run.py#session
    anchor: "start, known = start_of(r, seconds)"
  - actor: /components/importer-concept2.md
    label: validate, batch, and judge the snapshot
    action: "A cache file that will not read is logged and skipped, and the run then is not a snapshot. `poll` labels the batches only when every file read. The events go to `anam_submit` as in [submit a batch](/workflows/submit-a-batch.md)."
    writes: [/data-structures/envelope.md, /data-structures/batch-event.md]
    ends: true
    resource: concept2/run.py#run_over
    anchor: 'events = batch_events(payloads, str(config["person_id"]), snapshot and not logs)'
---

The split keeps the network out of the shaping. `fetch` is the source's reader and owns every failure a remote API has. `handle` and `poll` are pure over a folder of files, which makes them testable with a fake Logbook for `fetch` and plain files for the rest.
