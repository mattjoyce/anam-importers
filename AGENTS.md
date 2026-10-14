# AGENTS.md: anam-importers

- The contract is `docs/IMPORTERS.md` §8 in the anam repo. An importer that needs something
  the contract does not offer is a change to Anam first.
- An importer shapes payloads and nothing else: no identity, no joins, no summaries, no state
  of the record. It holds no token; `anam_submit` does.
- Python 3.10+, stdlib plus `jsonschema`. Plugins that need `jsonschema` use the uv script
  shebang so the gateway resolves it.
- A config key overrides every opinionated default (anam card 151). A value someone could
  reasonably choose differently (a limit, timeout, window, pattern or URL) is a key, snake_case,
  listed in the manifest's `config_keys` and documented in README with its default and why; the
  constant stays as the default. Each command reads its keys first through `anam_importer.config`,
  which range-checks them so a bad value fails at start, and passes the values down as
  parameters: nothing deeper reads config. A value that changing would break data or the contract
  with Anam (the batch cap, an identity, a Definition's vocabulary) stays a constant, commented
  "Not configurable" with why; one the Definition states is read from it. No test hooks: a test
  that needs another value sets the key or passes the parameter, never a module global.
  `docs/defaults-and-invariants.md` lists every value and its sort.
- Tests: `python3 -m unittest discover -s tests -t .`, and with `ANAM_BIN` set, against a real
  daemon. Prefer a real database file and a real daemon over mocks.
- Public-repo hygiene: no tokens, hosts, paths or personal identifiers in code or examples.
