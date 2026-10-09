# anam-importers

Version 0.1.0 · [Changelog](CHANGELOG.md) · [How it fits together](docs/explainer.html)

Importers put a source's data into [Anam](https://github.com/mattjoyce/anam), a personal
longitudinal record. Each importer is a [ductile](https://github.com/mattjoyce/ductile)
plugin that reads one source and shapes its rows to Facet Definitions it carries.
`anam_submit` posts the result to Anam under that importer's own token. Anam keeps the
Definitions, the admission gate and the record, and knows no vendor.

```text
source ──▶ importer (shape, validate) ──batch event──▶ anam_submit (publish, post) ──▶ Anam
           anam_withings                                one instance per importer        POST /v1/envelopes
```

The contract every importer complies with is `docs/IMPORTERS.md` §8 in the anam repo: the
wire format, tokens, all-or-nothing batches of at most 49, and what each status means.
`docs/explainer.html` here walks through it with diagrams.

## What is here

```text
anam_importer/        the shared base: Definitions, validation, batches, the client, the ductile protocol
anam_submit/          posts a batch: makes sure Anam publishes its Definitions, then submits it
withings/             anam_withings: the withings plugin's measurements as health.measurement
  definitions/        the Definitions it emits, in Anam's manifest format
tests/                unit tests, and tests against a real anam daemon (ANAM_BIN)
docs/explainer.html   how the pieces fit, for a reader new to it
```

## Requirements

- Python 3.10 or later, with `jsonschema` 4.18 or later. Importers that validate declare it
  in a uv script header, so a gateway with `uv` resolves it; `anam_submit` needs only the
  standard library.
- An Anam daemon with the importer routes (anam card 53 and later), and a line for each
  importer in its `importers_file`.
- A ductile gateway to run the plugins (protocol 2).

## Writing an importer

1. A folder named for the source, with `manifest.yaml`, `run.py` and `definitions/<type>.json`
   for each type it emits. A Definition is Anam's manifest format: closed JSON Schema in
   `schema`, identity and time in `meta`.
2. `run.py` reads the source and builds payloads, and does nothing else: no identity, no joins,
   no summaries. `anam_importer.envelope` wraps a payload, `check` validates every payload
   against its Definition before anything leaves, `batches` cuts them to the gate's 49.
3. Each batch is an event `<plugin>.batch` with `envelopes`, `definitions` (the manifests as
   text) and a `batch` label. A pipeline routes it to that importer's `anam_submit` instance.
4. Offer a resend-everything command. Anam makes it idempotent: an unchanged row is a no-op.
5. Raise `anam_importer.ductile.Failure(message, retry=...)` when the source fails, so the
   gateway knows whether trying again can help.

## Running the tests

```sh
python3 -m unittest discover -s tests -t .                                     # unit tests
ANAM_BIN=~/Projects/anam/bin/anam python3 -m unittest discover -s tests -t .   # and against a real daemon
```

## Versioning and releases

The repo has one [semantic version](https://semver.org/), in `VERSION`. The base,
`anam_submit` and every importer release together, and each plugin manifest carries the same
number; a test fails if any of them, or the changelog's newest release, disagrees.

- **Major**: a change an existing importer or gateway config must follow, such as a renamed
  event, a changed batch payload, or a base function removed.
- **Minor**: a new importer, command or base function; a new Definition version an importer
  emits.
- **Patch**: a fix that changes no interface.

To release: move the changelog's Unreleased entries under the new version, set `VERSION` and
every manifest's `version`, commit, tag `vX.Y.Z`, push the tag. A gateway that runs these
plugins then needs `ductile plugin lock` for each changed one.

## Wiring an importer into a gateway (Withings)

Not deployed. What it takes, in order:

1. **Token.** `openssl rand -hex 32` makes the importer's token. Its hash goes into Anam's
   `importers_file` (`ANAM_IMPORTERS_FILE`), and the daemon restarts to read it:

   ```yaml
   importers:
     - source: withings          # the built-in worker's source, so facets are the same facets
       token_sha256: <printf %s "$token" | sha256sum>
       types: [health.measurement]
   ```

   The token itself goes into the gateway's vault as `ANAM_IMPORTER_TOKEN`, granted to the
   `anam_submit_withings` instance only.

2. **Plugins.** This repo is a plugin root (the gateway image copies it in, as it does
   `ductile-withings`). Then:

   ```yaml
   plugins:
     anam_withings:
       enabled: true
       timeout: 120s
       retry:
         max_attempts: 3        # a locked withings database is retried
       schedules:
         - id: resend           # catches readings Withings revised: the withings plugin rewrites
           command: poll        # those rows in place and announces only new groups. A resend is
           every: 24h           # 113 batches, nearly all no-op, so once a day: a correction
           jitter: 1h           # reaches Anam within a day
       config:
         db_path: <the withings plugin's db_path>
         person_id: <Anam's person_id>
     anam_submit_withings:
       uses: anam_submit
       enabled: true
       timeout: 60s
       retry:
         max_attempts: 5        # a 503 while Anam ingests is retried
       config:
         anam_url: http://<anam host>:8787
   ```

3. **Pipelines.**

   ```yaml
   pipelines:
     - name: anam-withings-new-group
       on: withings.measurement_recorded
       steps:
         - uses: anam_withings
     - name: anam-withings-after-reconcile
       on: withings.reconciled     # handle resends everything: a reconcile can change old groups' attribution
       steps:
         - uses: anam_withings
     - name: anam-withings-submit
       on: anam_withings.batch
       steps:
         - uses: anam_submit_withings
   ```

4. `ductile plugin lock anam_withings`, `ductile plugin lock anam_submit`, `ductile config lock`,
   reload.

While Anam's binary still carries its own `withings` worker, both paths write the same facets
under the same source, and the importer's batches come back `no-op`, except where the two
render a value differently (below). Once they agree, the worker and its `imports.yaml` entry
go, and a later Anam release drops `health.measurement` from the binary so this folder's copy
becomes the registered one.

## Values: why `29.371`, not `29.371000000000002`

The withings plugin stores a measurement's value as a SQLite REAL, and a REAL has no text of
its own. Anam's Go worker reads it with `CAST(value AS TEXT)`, which its SQLite build renders
with 17 significant digits when 15 do not round-trip (`29.371000000000002`); SQLite 3.43 and
later render the shortest form (`29.371`). `anam_withings` writes the shortest decimal that
reads back as the same double (`repr`), which IEEE 754 fixes whatever reads it. Against the
live record that is 222 of 5,531 measurements written differently, each the same number.
