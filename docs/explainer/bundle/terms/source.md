---
type: term
title: Source
description: The name Anam attributes a fact to, set by the token an importer posts under and never by the importer's payload.
timestamp: 2026-10-17T00:00:00Z
---

A source is a short hyphenated name such as `withings` or `bp-csv`. Anam's importers file maps a token hash to a source and the facet types that token may write. Because identity includes the source, moving a data stream from one source name to another produces different facets, so a takeover keeps the old name when the old facets must stay the same facets.

In this repository the source is configured per `anam_submit` instance through `token_secret`, not in any importer. See [one token per submit instance](/decisions/one-submit-instance-per-importer-holds-the-token.md).
