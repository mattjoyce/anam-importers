# IEEE 1752.1 schemas, pinned

Copied unchanged from IEEE's `omh/1752` repository (https://opensource.ieee.org/omh/1752),
`schemas/sleep/` and `schemas/utility/`, at commit 7000803a101d (2026-08-03), the commit Anam pins
its own copies at. Each keeps its `$id` under `https://w3id.org/ieee/ieee-1752-schema/`; every file
`sleep-episode-1.0.json` reaches is here, so nothing is fetched.

`tests/test_conformance.py` holds each Definition whose `source_schema` names one of these, and the
payloads its importer writes, to the pinned schema.
