---
type: term
title: Anam
description: The service this repository feeds, which keeps one person's record as append-only facts and accepts data only through envelopes posted by importers.
timestamp: 2026-10-17T00:00:00Z
---

Anam is a separate project, with its own repository and its own explainer. For this repository only its edges matter. It publishes [Facet Definitions](/terms/facet-definition.md), authenticates each importer by a bearer token that names a [source](/terms/source.md), admits or refuses whole batches of [envelopes](/terms/envelope.md), and reports what it still holds from a source after a [snapshot](/terms/snapshot.md).

Read the [Anam explainer](https://github.com/mattjoyce/anam/tree/master/docs/explainer) for the gate, the ledger and the read side. Nothing here restates them.
