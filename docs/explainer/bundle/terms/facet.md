---
type: term
title: Facet
description: One immutable fact in Anam's record, made from a payload an importer sent, with a type, an identity, a fact time and a content hash.
timestamp: 2026-10-17T00:00:00Z
---

A facet is what Anam stores for an admitted envelope. Which fact it is comes from the [identity key](/terms/identity-key.md); whether it changed comes from a hash of the payload. Sending the same payload again is a [no-op](/terms/no-op.md), and sending a different payload for the same identity supersedes the facet with a new version while the old one stays.

Importers never see a facet, only the [admission receipt](/data-structures/admission-receipt.md) that says what happened to each envelope.
