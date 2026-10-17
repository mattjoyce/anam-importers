---
type: change-path
title: Add a config key
description: A value someone could reasonably choose differently becomes a snake_case key with its shipped default, read through the config helpers, listed in the manifest and the defaults document, and covered by the config test.
timestamp: 2026-10-17T00:00:00Z
resource: tests/test_config.py#PluginsTest
anchor: "def test_every_plugin_refuses_a_bad_value_at_start(self):"
basis: code
tier: detail
touches:
  - /components/config-helpers.md
  - /invariants/config-is-read-and-checked-once-at-start.md
  - /decisions/config-keys-for-defaults-constants-for-invariants.md
  - /data-structures/plugin-manifest.md
---

1. **Sort the value.** If changing it breaks data or the contract with Anam, it stays a constant with a comment saying why it is not configurable.
2. **Name it.** A snake_case key, a `DEFAULT_` constant with a comment saying why that number, and a range.
3. **Read it once.** Add it to the plugin's `Settings` tuple, read through `integer`, `number`, `text` or `url`, and pass the value down as a parameter. Nothing deeper reads config.
4. **Declare it.** Add it to the manifest's `config_keys.optional`, and to `docs/defaults-and-invariants.md` and the README table.
5. **Test it.** Add a bad-value case to `PluginsTest` that asserts `config <key>:` appears in the error. A test that needs another value sets the key and never changes a module global.
