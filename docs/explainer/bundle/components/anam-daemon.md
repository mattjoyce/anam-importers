---
type: component
title: Anam daemon
description: The external service that authenticates an importer's token, publishes Definitions, admits batches whole through its gate, and answers snapshot reports.
timestamp: 2026-10-17T00:00:00Z
resource: README.md#Snapshots and the absent alert
anchor: "## Snapshots and the absent alert"
basis: docs
tier: supporting
group: outside
depends_on: []
---

Not part of this repository. This repository relies on four of its behaviours. It refuses a batch over 49, it admits or refuses a batch whole, it composes identity and fact time from the Definition, and after the last part of a snapshot it reports facets it holds live that the run did not carry. Everything else about it is in the [Anam explainer](https://github.com/mattjoyce/anam/tree/master/docs/explainer).
