---
type: term
title: Fact time
description: The moment a fact was true in the world, read by Anam from a pointer in the payload using the Definition's layout and zone.
timestamp: 2026-10-17T00:00:00Z
---

A Definition's `time_semantics.fact_time` names a pointer, a Go-style time layout and a zone. Anam parses the payload value with them. Importers only have to put an unambiguous time at that pointer.

Three habits show up. A source that writes UTC instants uses zone UTC (Withings dates, DreamStation starts, OwnTracks hours). A source that writes local wall-clock time names its zone and the importer attaches the same zone, read from the Definition so it is stated once (blood pressure, Garmin days). An interval source points at the interval's start.
