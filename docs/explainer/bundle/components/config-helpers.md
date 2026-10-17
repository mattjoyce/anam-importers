---
type: component
title: Config helpers (anam_importer.config)
description: Reads and range-checks a plugin's config keys once at the start of a command, so a bad value fails there naming the key, before any source or Anam is touched.
timestamp: 2026-10-17T00:00:00Z
resource: anam_importer/config.py#integer
anchor: "def integer(config: Dict[str, Any], key: str, default: int, low: int, high: int) -> int:"
basis: code
tier: supporting
group: shared
depends_on:
  - /components/plugin-protocol.md
---

Five helpers cover the key kinds. `integer` and `number` take a default and an inclusive range (`number` can make the low end open, so a timeout of 0 is refused). `text` wants a non-empty string. `url` wants an http or https origin with a host and no query, fragment or credentials, so a token sent there goes nowhere else. `bad` builds the `Failure` with `retry=False` and the message `config <key>: ...`.

Plugins read their keys through these functions into a small settings tuple and pass the values down as parameters. Nothing deeper reads config. See [config is read once at the start](/invariants/config-is-read-and-checked-once-at-start.md). The `stays` importer does not yet use them, which is a [gap](/gaps/stays-reads-its-config-unchecked.md).
