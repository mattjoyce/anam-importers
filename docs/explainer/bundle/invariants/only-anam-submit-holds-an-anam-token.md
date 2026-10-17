---
type: invariant
title: Only anam_submit holds an Anam token
description: Importers read no Anam token and call no Anam endpoint, and anam_submit reads exactly the secret its instance names.
timestamp: 2026-10-17T00:00:00Z
resource: anam_submit/run.py#client_of
anchor: "def client_of(request: Dict[str, Any], s: Settings) -> Client:"
basis: code
tier: supporting
enforced_at: anam_submit/run.py#client_of
enforced_anchor: 'if not token:'
applies_to:
  - /components/anam-submit.md
  - /components/importer-withings.md
  - /components/importer-concept2.md
tested_by:
  - tests/test_submit.py#test_the_token_is_the_secret_config_names_and_nothing_else
---

The Concept2 importer's `fetch` takes a different secret, a Logbook token, which is not an Anam credential. No other importer takes a secret. The rule is held by structure, since only `anam_submit` constructs the Anam `Client` with a token, and reviewed in `AGENTS.md`.
