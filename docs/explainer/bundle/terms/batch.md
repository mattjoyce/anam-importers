---
type: term
title: Batch
description: At most 49 envelopes sent in one request, which Anam admits whole or refuses whole in a single transaction.
timestamp: 2026-10-17T00:00:00Z
---

`MAX_BATCH = 49` is the largest batch Anam takes. `batches` cuts a list of envelopes in order. An importer emits one [batch event](/data-structures/batch-event.md) per batch, labelled `i/n` so a log line says which part it was. See [a batch is at most 49](/invariants/a-batch-is-at-most-49.md).
