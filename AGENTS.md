# AGENTS.md: anam-importers

- The contract is `docs/IMPORTERS.md` §8 in the anam repo. An importer that needs something
  the contract does not offer is a change to Anam first.
- An importer shapes payloads and nothing else: no identity, no joins, no summaries, no state
  of the record. It holds no token; `anam_submit` does.
- Python 3.10+, stdlib plus `jsonschema`. Plugins that need `jsonschema` use the uv script
  shebang so the gateway resolves it.
- Tests: `python3 -m unittest discover -s tests -t .`, and with `ANAM_BIN` set, against a real
  daemon. Prefer a real database file and a real daemon over mocks.
- Public-repo hygiene: no tokens, hosts, paths or personal identifiers in code or examples.
