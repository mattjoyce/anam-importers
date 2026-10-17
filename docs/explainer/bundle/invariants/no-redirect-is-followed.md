---
type: invariant
title: No redirect is followed with a token
description: A 3xx answer from Anam or from the Logbook is an error, so a bearer token never reaches another host, port or scheme.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/client.py#Client
anchor: "if 300 <= resp.status < 400:"
basis: code
tier: supporting
enforced_at: anam_importer/client.py#Client
enforced_anchor: "not followed; set anam_url to the daemon itself"
applies_to:
  - /components/anam-client.md
  - /components/importer-concept2.md
tested_by:
  - tests/test_client.py#test_no_redirect_is_followed_so_the_token_stays_on_its_origin
  - tests/test_concept2.py#test_a_redirect_is_refused_so_the_token_stays_home
---

The URL itself must be an http or https origin with a host and no query, fragment or credentials, checked in `Client.__init__` and by `config.url`. The redirect error tells the operator to set the URL to the service itself.
