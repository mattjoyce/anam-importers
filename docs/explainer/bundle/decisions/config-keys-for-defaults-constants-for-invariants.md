---
type: decision
title: A config key for every default, a constant for every invariant
description: A value someone could reasonably choose differently is a snake_case config key with its shipped default, range-checked at start, and a value whose change breaks data or the contract stays a commented constant.
timestamp: 2026-10-17T00:00:00Z
resource: docs/defaults-and-invariants.md#Defaults (config keys)
anchor: "## Defaults (config keys)"
basis: docs
tier: supporting
alternatives:
  - Hard-code every value, which makes a slower network or a different sync schedule a code change.
  - Make every value a key, which lets someone configure a batch size that Anam will refuse.
affects:
  - /components/config-helpers.md
  - /invariants/config-is-read-and-checked-once-at-start.md
  - /change-paths/add-a-config-key.md
---

**Choice.** The list in `docs/defaults-and-invariants.md` sorts every hard-coded value. Defaults are keys (timeouts, response caps, lookback windows, busy timeouts, a file glob, the Logbook URL and user, a payload bound, the stay thresholds). Invariants stay constants with a comment saying why they are not configurable (`MAX_BATCH`, `MAX_EXT`, the outcome words, the Definition's vocabulary).

**Why.** A bad value fails at the start of a command naming the key, so a typo cannot reach a source or Anam. A test that needs another value sets the key or passes a parameter and never changes a module global.
