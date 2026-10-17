---
type: term
title: Lookback window
description: The number of days of recent files or messages that a handle run re-reads, set by the lookback_days key, because the source has no cursor and the importer keeps no state.
timestamp: 2026-10-17T00:00:00Z
---

Garmin, Concept2, OwnTracks and stays accept a `lookback_days` key (defaults 3, 3, 2 and 2). A `handle` run reads only what changed in that window, based on file modification time or message receipt time. The window is a default, not an invariant, because how often a source syncs is the operator's fact. A `poll` run ignores it and reads everything.
