---
type: decision
title: One submit instance per importer holds the token
description: Importers hold no Anam token. A generic anam_submit plugin posts for all of them, run as one instance per importer so each token is reachable only by the plugin that uses it.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/run.py#client_of
anchor: "global, so each instance names its importer's own: token_secret."
basis: code
tier: supporting
alternatives:
  - Every importer holds its own token and posts for itself, which spreads Anam's endpoints, retries and the absent alert across nine plugins.
  - One shared token for all importers, which gives up Anam's per-source scoping, because the token is what names the source.
affects:
  - /components/anam-submit.md
  - /terms/source.md
  - /components/ductile-gateway.md
tested_by:
  - tests/test_submit.py#test_the_token_is_the_secret_config_names_and_nothing_else
---

**Choice.** An importer ends at a batch event. A pipeline routes `anam_<plugin>.batch` to an `anam_submit` instance whose config names a secret (`token_secret`) holding that importer's token. The gateway grants the secret to that instance only.

**Why.** The token names the source and bounds the types it may write. Keeping it out of the importers means a parser bug in one source cannot leak or misuse it, and all the HTTP, retry and snapshot logic exists once. A secret name is global in the gateway's vault, so each importer needs its own name and its own instance.

**What it costs.** Each importer needs two plugin entries and two pipelines, and a mismatch between the instance and the token's source surfaces only as a refusal from Anam. `health` on the instance proves the URL and the token.
