---
type: workflow
title: Run a plugin by hand
description: Any importer or anam_submit runs from a shell with one JSON request on stdin, and answers with one JSON response on stdout, the same contract the gateway uses.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/ductile.py#run
anchor: "request = json.load(sys.stdin)"
basis: code
tier: supporting
trigger: A person pipes a request into a plugin's run.py, for example echo a JSON object with command poll and the plugin's config into uv run withings/run.py.
steps:
  - actor: /components/plugin-protocol.md
    caller: outside
    label: read one JSON object from stdin
    action: "`run` calls `json.load` on stdin. Invalid JSON, or JSON that is not an object, gets an error response with `retry` false and no handler runs."
    reads: [/data-structures/plugin-request.md]
    resource: anam_importer/ductile.py#run
    anchor: "request = json.load(sys.stdin)"
  - actor: /components/plugin-protocol.md
    label: look up the command
    action: "The command is trimmed and lower-cased, then found in the plugin's handler map. An unknown name gets an error response that names it."
    resource: anam_importer/ductile.py#run
    anchor: 'json.dump(error(f"unknown command {command!r}", retry=False), sys.stdout)'
  - actor: /components/importer-withings.md
    caller: /components/plugin-protocol.md
    label: run the handler
    action: "For `poll`, the Withings handler reads its database and returns an ok response with batch events. The handler is an ordinary function, so tests call it in process or as a subprocess."
    resource: withings/run.py#poll
    anchor: "return batch_events(request, None)"
  - actor: /components/config-helpers.md
    caller: /components/importer-withings.md
    label: check config before touching a source
    action: "Each command reads its keys first. A key of the wrong kind or out of range raises a non-retryable `Failure` that names the key, before any file is opened or Anam called."
    resource: anam_importer/config.py#bad
    anchor: 'return Failure(f"config {key}: {why}", retry=False)'
  - actor: /components/plugin-protocol.md
    label: turn any failure into an error response
    action: "An `AnamError` or `Failure` becomes an error carrying its own `retry`. Any other exception becomes an error that is not worth retrying. No traceback reaches stdout."
    resource: anam_importer/ductile.py#run
    anchor: "except (AnamError, Failure) as exc:"
  - actor: /components/plugin-protocol.md
    label: write one response and exit
    action: "Whatever happened, stdout holds exactly one JSON object, which a person reads as text and the gateway parses."
    writes: [/data-structures/plugin-response.md]
    ends: true
    resource: anam_importer/ductile.py#run
    anchor: "json.dump(response, sys.stdout)"
---

To post a batch by hand, run `anam_submit/run.py` with a request whose `event.payload` is one of the batch events an importer returned, whose `config` holds `anam_url` and `token_secret`, and whose `secrets` maps that name to the importer's token. The test suite does exactly this through `run_plugin`.
