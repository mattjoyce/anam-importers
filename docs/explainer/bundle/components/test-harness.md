---
type: component
title: Test harness (tests/helpers.py)
description: Helpers that build a Withings-shaped database, run a plugin as a subprocess, and start a real anam daemon on a temporary ledger with one importer token.
timestamp: 2026-10-17T00:00:00Z
resource: tests/helpers.py#Daemon
anchor: "class Daemon:"
basis: code
tier: detail
group: tools
depends_on:
  - /components/anam-daemon.md
---

`run_plugin` is the same call the gateway makes, the request on stdin and the response from stdout, so the tests exercise the protocol as well as the functions. `Daemon` writes an importers file with a random token, picks a free loopback port, and runs `anam init` and `anam daemon` from the binary named by `ANAM_BIN`. Tests that need it skip without that variable. See [check an importer against a real daemon](/workflows/check-an-importer-against-a-real-daemon.md).
