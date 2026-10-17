---
type: decision
title: Importers keep no state and resend everything
description: An importer remembers nothing between runs, so every source gets a poll command that sends all it holds, and Anam's no-op on an unchanged payload makes that safe and a snapshot makes it informative.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/envelopes.py#snapshot_parts
anchor: "Only a run that sends everything the source holds of types may label"
basis: code
tier: core
alternatives:
  - Keep a cursor or a sent-set per importer, which adds state that can drift from the record and must itself be backed up and rebuilt.
  - Send only new rows and never reconcile, which cannot notice a source that dropped a fact.
affects:
  - /components/envelopes.md
  - /terms/snapshot.md
  - /workflows/send-a-records-folder.md
  - /components/rebuild-drill.md
---

**Choice.** Each importer has `handle` for a recent change and `poll` for everything. The idempotent commit at Anam makes resending an unchanged row a no-op, so no importer needs to know what it sent before. A `poll` run labels its batches with `snapshot_parts`, which lets Anam say what it holds from the source that the run no longer carries.

**Why.** It makes an importer a pure function of its source. The same property is what lets the [rebuild drill](/workflows/rebuild-the-record-from-the-importers.md) build a whole ledger from the importers alone. The only recent-window state is the `lookback_days` key, which is a performance bound and not a cursor.

**What it costs.** A full resend of a large source is slow and heavy. A DreamStation card of about 1,300 sessions is 27 batches, and a network share makes reading it slow. The importers accept that cost, with `handle` as the cheap path where the source supports it.
