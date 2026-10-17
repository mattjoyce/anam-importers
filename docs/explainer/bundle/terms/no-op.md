---
type: term
title: No-op
description: The outcome Anam gives an envelope whose payload hash matches the facet it already holds, which is what makes resending everything safe.
timestamp: 2026-10-17T00:00:00Z
---

The four outcomes in a receipt are `admitted`, `superseded`, `no-op` and `tombstoned`, listed as `OUTCOMES` in the client. An importer cannot tell a no-op from an admission before it sends, and does not try. It sends everything the source holds and reads the counts in `anam.admitted`.
