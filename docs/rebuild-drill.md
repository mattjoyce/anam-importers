# The rebuild drill

`scripts/rebuild-drill.py` proves that Anam owns no facts: it builds a fresh ledger from the
importers alone and compares it with the live one. The procedure it follows, and
what a rebuild cannot bring back, is `docs/IMPORTERS.md` §8.8 in the anam repo.

## What it does

1. Runs each importer in the plan with `poll`, its resend-everything command, the same request the
   gateway sends. Each importer's types are the ones its poll emits.
2. Starts a scratch `anam daemon` on a new ledger in the work directory, accepting each importer
   under a fresh token, and answering reads whole (`max_read_bytes: 0`).
3. Sends every batch through `anam_submit`, as the gateway does. A Definition the importer emits is
   registered by its first batch, as on the live daemon.
4. With `--live-url`, reads each type from both daemons and compares, for the plan's sources only,
   the facet ids each holds and each facet's content hash and status. It only reads the live daemon.

The last submit of each importer says whether its snapshot completed and how many live facets it
left absent; a rebuild from nothing leaves none.

## The plan

JSON, one entry per importer: its source name, its folder in this repository, and the instance
config the gateway gives it. Paths are wherever the sources are seen from the machine that runs the
drill.

```json
{"person_id": "<the record's person>",
 "importers": [
  {"source": "records", "plugin": "records",
   "config": {"records_dir": "<library>/records", "person_id": "<person>"}},
  {"source": "documents", "plugin": "documents",
   "config": {"documents_dir": "<library>/documents", "person_id": "<person>"}},
  {"source": "withings", "plugin": "withings",
   "config": {"db_path": "<withings.db>", "person_id": "<person>"}}
 ]}
```

Copy each importer's `config` from its instance in the gateway's `plugins.yaml`, changing only the
paths. The plan's top-level `person_id` is the live record's person; the scratch daemon is pinned to
it, as the live one is.

## Running it

```sh
scripts/rebuild-drill.py --anam <anam binary> --plan plan.json --work <new directory> \
    --live-url <live daemon> --live-token-file <operator token file>
```

It needs the anam binary of the live daemon's version, `uv` for the importers' scripts, and read
access to every source in the plan. The work directory keeps the scratch ledger, `daemon.log` and
`report.json` (outcomes, the comparison by type, seconds per step). Delete it afterwards; it holds a
copy of the record.

## Reading the result

Each type prints `live`, `scratch`, `only-live`, `only-scratch` and `differ`. A clean drill is all
zeros in the last three. Anything else is one of:

- a source that no longer holds a fact the record still does (only-live): expected for a retired
  source, a bug otherwise;
- a fact the live record retracted that the source still holds (only-scratch);
- a payload the importer now shapes differently from when it was admitted (differ): the live record
  holds an older shaping, and a resend to it would supersede.

`report.json` names each by its `source_ref`.
