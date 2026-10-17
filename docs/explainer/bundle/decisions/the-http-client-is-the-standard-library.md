---
type: decision
title: The HTTP clients use the standard library
description: Anam calls and Concept2 calls use http.client with a single deadline and no redirects, and the only third-party imports are jsonschema, pyyaml and two pinned decoders in script headers.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/client.py#Client
anchor: "import http.client"
basis: code
tier: detail
alternatives:
  - A requests-style library, which follows redirects by default and keeps its own timeouts per phase.
  - urllib.request, which follows redirects through handlers a caller must remove.
affects:
  - /components/anam-client.md
  - /components/importer-concept2.md
  - /components/geocoder.md
---

**Choice.** `http.client` with one `time.monotonic()` deadline across connect, headers and body, and a read loop that counts bytes. `anam_submit` needs only the standard library. Plugins that validate carry `jsonschema` in a uv script header, the records and documents importers carry `pyyaml`, and the Garmin and DreamStation importers pin their decoders.

**Why.** The rules matter more than the convenience. A token must never follow a redirect, a call must fail fast under one deadline, and an answer must be bounded. Owning the few lines is simpler than configuring a library to behave that way.
