---
type: term
title: Envelope
description: The one message Anam accepts, a facet type, a Definition version and a payload, with an optional asserted person and nothing that names a source.
timestamp: 2026-10-17T00:00:00Z
---

An envelope is `{type, definition_version, payload}` plus `asserted_person` when the source says whom the data belongs to. The importer builds it with [envelopes](/components/envelopes.md). The shape is in [Envelope](/data-structures/envelope.md).

It has no `source` and no `source_ref`. The token names the source, and Anam composes the identity from the Definition's [identity key](/terms/identity-key.md). An importer that tried to send either would be refused at the gate.
