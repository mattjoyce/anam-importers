---
type: workflow
title: Submit a batch
description: A batch event emitted by any importer becomes admitted facets in Anam, with the documents stored first, the Definitions published, the receipt checked and an alert raised when a complete resend left facets absent.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/run.py#handle
anchor: "admission = client.submit(envelopes, snapshot)"
basis: code
tier: core
trigger: An importer's run returns an event named anam_<plugin>.batch, for example anam_withings.batch, and a pipeline routes it to that importer's anam_submit instance.
steps:
  - actor: /components/ductile-gateway.md
    caller: outside
    label: route the batch to its submit instance
    action: "A pipeline names the importer's batch event as its trigger and anam_submit as its step. The gateway starts the instance named there, with that instance's config and only the vault secrets it names, and passes the event."
    reads: [/data-structures/batch-event.md, /data-structures/plugin-manifest.md]
    resource: anam_submit/manifest.yaml#config_keys
    anchor: "required: [anam_url, token_secret]"
  - actor: /components/plugin-protocol.md
    caller: /components/ductile-gateway.md
    label: read the request and find handle
    action: "`run` parses one JSON object from stdin, lower-cases the command, and looks it up in the handler map. An unknown command or bad JSON gets a structured error and no handler runs."
    reads: [/data-structures/plugin-request.md]
    resource: anam_importer/ductile.py#run
    anchor: "handler = handlers.get(command)"
  - actor: /components/anam-submit.md
    label: build a client under the granted token
    action: "`settings` range-checks `timeout`, `max_response_bytes` and `absent_ids_shown`. `client_of` reads the secret whose name `token_secret` holds, and refuses a missing name or an ungranted secret before any call. Vault names are global, so each instance names its own importer's token."
    reads: [/data-structures/plugin-request.md]
    resource: anam_submit/run.py#client_of
    anchor: 'token = (request.get("secrets") or {}).get(name, "")'
  - actor: /components/anam-client.md
    caller: /components/anam-submit.md
    label: post each named document's bytes
    action: "Only a batch with a `documents` list does this, before the envelopes. The extension is taken from the name, and left off when it is not letters and digits or is over 16 characters. See [hand over a document](/workflows/hand-over-a-document.md)."
    reads: [/data-structures/document-ref.md]
    resource: anam_importer/client.py#store_document
    anchor: 'target = "/v1/documents?" + urllib.parse.urlencode({"ext": ext})'
  - actor: /components/definitions.md
    caller: /components/anam-submit.md
    label: make sure Anam publishes the Definitions
    action: "For each manifest the batch carries, ask Anam for that type and version. A 404 registers the body. A different body at a held version stops the run with a non-retryable error, and nothing is submitted."
    reads: [/data-structures/definition-manifest.md]
    resource: anam_importer/definitions.py#ensure_published
    anchor: "published = client.definition(d.type, d.version)"
  - actor: /components/anam-submit.md
    label: stamp current versions when asked
    action: "A batch with `current_versions` set has no version of its own, as with a records file. `stamp_current` lists Anam's Definitions and fills `definition_version` on each envelope that lacks one. A type Anam does not publish is left for the gate to refuse."
    reads: [/data-structures/batch-event.md]
    resource: anam_submit/run.py#stamp_current
    anchor: 'current = {d["type"]: d["current"] for d in client.definitions()}'
  - actor: /components/anam-client.md
    caller: /components/anam-submit.md
    label: post the envelopes with the bearer token
    action: "`submit` sends `{envelopes, snapshot?}` as compact JSON with `Authorization: Bearer` and an `Anam-Timeout` header, over `http.client`, under one deadline for connect, headers and body. A redirect is an error."
    writes: [/data-structures/envelope.md]
    resource: anam_importer/client.py#submit
    anchor: 'status, body = self._call("POST", "/v1/envelopes", payload)'
  - actor: /components/anam-daemon.md
    caller: /components/anam-client.md
    label: admit or refuse the whole batch
    action: "Anam resolves the token to a source, validates every envelope against its Definition, and admits all or none. Each envelope's outcome is one of the words in `OUTCOMES`. A refusal is a 422 listing every envelope and its reason."
    resource: anam_importer/client.py#OUTCOMES
    anchor: 'OUTCOMES = {"admitted", "superseded", "no-op", "tombstoned"}'
  - actor: /components/anam-client.md
    caller: /components/anam-submit.md
    label: accept only a whole receipt
    action: "`admission` requires a positive `w`, one result per envelope with a distinct in-range index and a known outcome, and `changed` equal to the admitted plus superseded count. Anything less is a retryable error and no admitted event is emitted. A 422 raises `Refused`, which `handle` turns into a non-retryable error that logs each reason."
    writes: [/data-structures/admission-receipt.md]
    resource: anam_importer/client.py#admission
    anchor: 'if len(indexes) != sent or a["changed"] != changed:'
  - actor: /components/anam-submit.md
    label: report the counts as anam.admitted
    action: "`handle` tallies outcomes and emits `anam.admitted` with `w`, `changed`, the outcome counts and the batch label, and the run's result line reads like `3 admitted at W 41`."
    writes: [/data-structures/plugin-response.md]
    resource: anam_submit/run.py#handle
    anchor: 'events = [ductile.event("anam.admitted", {'
  - actor: /components/anam-client.md
    caller: /components/anam-submit.md
    label: read the report on the last part
    action: "Only when the receipt says the batch's snapshot is complete. The report holds `complete`, and then `live`, `absent`, `carried` and `absent_ids`."
    reads: [/data-structures/snapshot-label.md]
    resource: anam_importer/client.py#snapshot
    anchor: 'path = "/v1/snapshots/" + urllib.parse.quote(snapshot_id, safe="")'
  - actor: /components/anam-submit.md
    label: alert on absent facets, retract nothing
    action: "When `absent` is above zero, `absent_event` emits `anam.snapshot_absent` with the counts and at most `absent_ids_shown` ids, keyed on the snapshot id so a resent last part does not alert twice. Retraction stays with the operator."
    ends: true
    resource: anam_submit/run.py#absent_event
    anchor: "anam.snapshot_absent:{snapshot['id']}"
---

Every importer ends here, so the path is the same whatever the source. The importer's work is finished once it has emitted its batch events, and `anam_submit` never inspects a payload. It checks only that Anam publishes the Definitions, that the receipt is whole, and what a complete snapshot left behind.

Retrying is safe at every step. Anam admits a batch whole or not at all, and a resent unchanged batch is all no-op, so a timeout after the write costs one resend and no duplicates. The retry flag on each error says which failures can pass. A 5xx, a 429 and a transport failure can, and a refusal or any other 4xx cannot.

The daemon's side of steps 8 and 9 is in the [Anam explainer](https://github.com/mattjoyce/anam/tree/master/docs/explainer). Related: [the client trusts only a whole receipt](/decisions/the-client-trusts-only-a-whole-receipt.md), [one submit instance per importer](/decisions/one-submit-instance-per-importer-holds-the-token.md).
