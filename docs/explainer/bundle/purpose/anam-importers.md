---
type: purpose
title: anam-importers, the sources that feed Anam
description: Python plugins that each read one source of a person's data, shape its rows to a Facet Definition, and hand them to Anam as envelopes under their own token, so Anam holds the record and knows no vendor.
timestamp: 2026-10-17T00:00:00Z
commit: 2b5dfd2b5ef330412d5d3dec1eb22b4e2c5917d4
primary_workflow: /workflows/submit-a-batch.md
basis: code
---

## The problem

[Anam](/terms/anam.md) is a service that keeps one person's longitudinal record as immutable facts. It deliberately reads no source itself. Something has to turn a watch database, a blood pressure app export, a CPAP card or a folder of scanned documents into the one shape Anam accepts, the [envelope](/terms/envelope.md), and say which [Facet Definition](/terms/facet-definition.md) each row follows.

This repository is that something. It holds a small shared Python package (`anam_importer`), one generic posting plugin (`anam_submit`), and one plugin per source. Each [importer](/terms/importer.md) knows exactly one vendor's file layout. Everything after the shaping is the same code for every source, so a new source costs one folder and no change to Anam.

The plugins speak the [ductile](/terms/ductile.md) plugin protocol, so a gateway can run them on a schedule or on a file event. The protocol is plain enough to run one by hand, one JSON request on stdin and one JSON response on stdout.

## Who it is for

Someone who runs Anam for themselves and has data in several systems. The sources here are one person's (a Garmin watch, Withings scales, a blood pressure app, a CPAP card, a rowing logbook, a phone's location log, hand-written records), offered as working patterns for other sources. Times default to Australia/Sydney where a source writes local time.

The daemon side of the contract (the admission gate, tokens, the ledger) is described in the [Anam explainer](https://github.com/mattjoyce/anam/tree/master/docs/explainer) and the contract itself, `docs/IMPORTERS.md` section 8 in that repository.

## What it does not do

- It composes no identity. An envelope names no source and no source reference. The token names the source, and Anam derives identity from the Definition.
- It holds no token. Only `anam_submit` is given one, from the gateway's secret store, one instance per importer.
- It joins nothing and summarises nothing. A weekly average is a read over facets, not a facet.
- It keeps no state of its own. Every importer can resend everything it knows, and Anam makes an unchanged row a no-op.
- It never retracts. When a complete resend lacks facets Anam still holds, `anam_submit` raises an alert and the operator decides.
- It does not schedule itself. A gateway, or a person, decides when a plugin runs.
