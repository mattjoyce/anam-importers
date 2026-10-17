---
type: term
title: ductile
description: A gateway that runs small plugins on schedules and events, passing each one JSON on stdin and routing the events it returns, used here to run importers.
timestamp: 2026-10-17T00:00:00Z
---

ductile is a gateway (a separate project at https://github.com/mattjoyce/ductile) that runs plugins as child processes. It decides when, from a schedule or an event such as a file appearing, and routes the events a plugin returns to the next plugin through pipelines. It also holds secrets in a vault and hands a plugin only the ones its instance config names.

An importer does not need ductile to work. The [plugin protocol](/components/plugin-protocol.md) is one JSON object in and one out, so every plugin runs from a shell. See [run a plugin by hand](/workflows/run-a-plugin-by-hand.md).
