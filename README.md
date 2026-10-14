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

These are one person's importers, for the sources one person has: a Garmin watch through
GarminDB, Withings scales, a blood pressure phone app, a DreamStation CPAP card, Concept2's
Logbook, OwnTracks on a phone, and records files written by hand. Times default to
Australia/Sydney. They are offered as working patterns for your own sources, not as a product.
Every value in `tests/` is made up.

## What is here

```text
anam_importer/        the shared base: Definitions, validation, batches, the client, the ductile protocol
anam_submit/          posts a batch: makes sure Anam publishes its Definitions, then submits it
withings/             anam_withings: the withings plugin's measurements as health.measurement
bp_csv/               anam_bp_csv: a blood pressure app export as health.blood-pressure (OMH)
dreamstation_card/    anam_dreamstation: a DreamStation CPAP card copy as sleep.cpap-session
records/              anam_records: records files, facts written down as YAML, as Anam's bundled types
documents/            anam_documents: a folder of documents with sidecars as doc.reference; anam_submit hands the bytes to Anam's library
  extract/            one-off extractors that turn an export into a records file
garmin/               anam_garmin: a Garmin watch's alerts, sessions, sleep, heart rate, steps and days from GarminDB
concept2/             anam_concept2: Concept2 Logbook workouts as exercise.session
owntracks/            anam_owntracks: a phone's OwnTracks positions as location.track, one facet per hour
  definitions/        the Definitions it emits, in Anam's manifest format
tests/                unit tests, and tests against a real anam daemon (ANAM_BIN)
docs/explainer.html   how the pieces fit, for a reader new to it
docs/defaults-and-invariants.md   every hard-coded value: a config key's default, or a constant and why
```

## Requirements

- Python 3.10 or later, with `jsonschema` 4.18 or later. Importers that validate declare it
  in a uv script header, so a gateway with `uv` resolves it; `anam_submit` needs only the
  standard library.
- An Anam daemon with the importer routes and snapshots (anam card 78, a14ee51 and later), and a
  line for each importer in its `importers_file`.
- A ductile gateway to run the plugins on a schedule (protocol 2). Without one, a plugin is a
  program that reads one JSON request on stdin and writes one JSON response on stdout, so you
  can run it by hand:

  ```sh
  echo '{"command": "poll", "config": {"db_path": "withings.db", "person_id": "me"}}' \
    | uv run withings/run.py
  ```

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
6. A limit, timeout, window or pattern is a config key whose default is the value you would
   have hard-coded, read and range-checked by `anam_importer.config` at the start of each
   command. A value the data or Anam depends on stays a constant, commented why
   (`docs/defaults-and-invariants.md`, anam card 151).

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

## Snapshots and the absent alert

A resend-everything run (Withings' `poll` and its resend after a reconcile, blood pressure's
`poll` over every export, every DreamStation run) labels its batches as the parts of one
snapshot. Anam then knows what the source still holds, and reports what it holds live from that
source that the run did not carry (`docs/IMPORTERS.md` §8.6 in the anam repo). Nothing is ever
retracted on its own: the operator runs `anam retract <source>`.

When the part that completes a snapshot finds facets absent, `anam_submit` raises
`anam.snapshot_absent` with the counts and up to 20 facet ids (`absent_ids_shown`, below), keyed on
the snapshot so a resent part does not alert twice. Route it to whatever tells the operator:

```yaml
pipelines:
  - name: anam-snapshot-absent
    on: anam.snapshot_absent
    steps:
      - uses: <the gateway's notifier, such as discord>
```

Needs an Anam with card 78 (anam a14ee51 or later). An older one refuses the `snapshot` field.

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

   The token itself goes into the gateway's vault as `anam_importer_token_withings`, granted
   to the principal `anam-submit-withings` only, which the `anam_submit_withings` instance
   names in `vault_principal`. Vault secret names are lowercase and global,
   so each importer's token has its own name, and its `anam_submit` instance names it in
   `token_secret`.

2. **Plugins.** This repo is a plugin root (the gateway image copies it in, as it does
   `ductile-withings`). Then:

   ```yaml
   plugins:
     anam_withings:
       enabled: true
       timeouts:                # per command; ductile has no flat timeout
         handle: 120s
         poll: 120s
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
       requires_vault: true                  # fail closed: no token, no spawn
       vault_principal: anam-submit-withings # the principal granted the token
       timeouts:
         handle: 60s
       retry:
         max_attempts: 5        # a 503 while Anam ingests is retried
       config:
         anam_url: http://<anam host>:8787
         token_secret: anam_importer_token_withings
   ```

   Optional keys, each with the default it ships with:

   | Key | Plugin | Default | Why |
   |---|---|---|---|
   | `busy_timeout_ms` | `anam_withings` | 5000 | how long a read waits for the withings plugin's write before it asks to be retried |
   | `timeout` | `anam_submit` | 30 | seconds one call to Anam may take, connect to last byte; more than 0, at most 3600 |
   | `max_response_bytes` | `anam_submit` | 8388608 (8 MiB) | the most one answer from Anam may hold; the largest it sends is a snapshot report of 1,000 ids, under 1 MiB |
   | `absent_ids_shown` | `anam_submit` | 20 | how many absent facet ids `anam.snapshot_absent` carries, 0 to 1000; `anam retract` lists them all |

   A value of the wrong kind or out of range fails the command at start, naming the key.

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

## Wiring an importer into a gateway (blood pressure)

Not deployed. The same steps as Withings, with these differences:

1. **Token.** Source `bp-csv` (the built-in worker's), types `[health.blood-pressure]`, secret
   `anam_importer_token_bp_csv`, principal `anam-submit-bp-csv`.

2. **Plugins.** The export arrives as a file, so `folder_watch` runs the importer, one event per
   file:

   ```yaml
   plugins:
     bp_export_watch:
       uses: folder_watch
       enabled: true
       parallelism: 1
       schedules:
         - every: 5m
       config:
         watches:
           - id: bp_exports
             root: <the folder exports are dropped in>
             event_type: bp.export
             include_globs: ["BloodPressure_*"]
             emit_mode: per_file
     anam_bp_csv:
       enabled: true
       timeouts:
         handle: 60s
         poll: 60s
       config:
         person_id: <Anam's person_id>
         export_dir: <the folder that keeps every export, for poll>
     anam_submit_bp_csv:
       uses: anam_submit
       enabled: true
       requires_vault: true
       vault_principal: anam-submit-bp-csv
       timeouts:
         handle: 60s
       retry:
         max_attempts: 5
       config:
         anam_url: http://<anam host>:8787
         token_secret: anam_importer_token_bp_csv
   ```

3. **Pipelines.** `bp.export` to `anam_bp_csv`, and `anam_bp_csv.batch` to `anam_submit_bp_csv`.

`pattern` (default `BloodPressure_*`, the app's export names) is the glob `poll` and `handle` find
exports under `export_dir` by; set it if your exports are named otherwise.

`poll` resends every export under `export_dir`, so a rebuild reruns them all. Keep every export
there; an overlapping later export admits only its new readings. The importer reads the file and
never moves or deletes it. Exports are ordered by the date the app writes into the name
(`BloodPressure_9-October-2026`), and a reading two exports hold is sent once, from the newer, so
a comment corrected in a later export stands and a resend stays `no-op`. With `export_dir` in its
config, `handle` also leaves alone the readings a newer export holds, so an old export dropped in
late cannot undo a correction.

Against the 234 readings of the July 2026 export already in the record, a resend through the
importer is 234 `no-op`: it is the built-in `bpcsv` worker's logic, moved, so the worker and its
`imports.yaml` entry can go as soon as it is live.

## Wiring an importer into a gateway (DreamStation)

Not deployed. Source `dreamstation`, types `[sleep.cpap-session]`, secret
`anam_importer_token_dreamstation`, principal `anam-submit-dreamstation`. Unlike the other
two, this importer registers its own Definition: Anam's binary does not bundle
`sleep.cpap-session`, so the first batch makes `anam_submit` register it.

It needs Python 3.11 and the [dreamstation](https://github.com/mattjoyce/dreamstation) decoder,
which its uv script header pins to a tag, fetched as a zip archive so the gateway needs no git.
The card copy is refreshed every few months by copying the SD card again, so a `folder_watch` on
the copy's `LAST.TXT` runs `handle`, and every run sends the whole card: the old sessions come
back `no-op` and the new ones are admitted.

```yaml
plugins:
  anam_dreamstation:
    enabled: true
    timeouts:
      handle: 120s
      poll: 120s
    config:
      card_path: <the card copy's P-SERIES directory>
      person_id: <Anam's person_id>
```

Every run is labelled a snapshot, unless the decoder skipped a file: an events file whose summary
is not on the card is part of a session the run cannot send, so that run carries no label and
`health` says why. A file the decoder cannot read fails the run instead.

A card of 1,317 sessions is 27 batches and about 1.9 MB on stdout. Read over a network share
it is slow (about 90 s for 2,600 small files); on local disk, under 3 s.

## Wiring an importer into a gateway (records)

Not deployed. Source `records`, the same name Anam's built-in worker used, so the cut-over is
no-op. Types are the ones the worker's scope named: `lab.result`, `lab.panel`, `condition.noted`,
`donation.blood`, `health.weight`, the `med.*`, `illness.*` and `travel.*` types, `visit.clinic`,
`gym.visit`, `exercise.session`, `health.blood-pressure` and `note.annotation`. Secret
`anam_importer_token_records`, principal `anam-submit-records`.

A records file names no Definition version, and every type it carries is bundled in Anam, so the
importer carries no Definitions. Each batch sets `current_versions`, and `anam_submit` shapes its
envelopes to the version Anam publishes as current, which is what the built-in worker did.

The records are read as the worker read them, with Go's yaml.v3 rules rather than YAML 1.1:
`yes` stays text, `0777` is 511, `1_000` is 1000, and a date is the text that was written. A number
Python would write differently from Go (`0.00001`, which Go writes plain and Python as `1e-05`)
stops the run and names the record, since the gate keeps a number's text and a different one
would supersede.

```yaml
plugins:
  anam_records:
    enabled: true
    config:
      records_dir: <the records folder>
      person_id: <Anam's person_id>
```

A `folder_watch` on the folder runs `handle`, and every run sends the whole folder as one
snapshot of the types it carries. A type whose every record is removed is not in the run, so it
is not reported absent.

## Wiring an importer into a gateway (documents)

Not deployed (anam card 103). Source `documents`, the name Anam's built-in worker used, so the
cut-over is no-op: each file's identity is its folder-relative path, and the payload is the
sidecar's fields plus the `path`, `sha256`, `bytes` and `media_type` measured from the file, as
the worker wrote them. Type `doc.reference`. Secret `anam_importer_token_documents`, principal
`anam-submit-documents`; the importer entry in Anam's `importers.yaml` names `types:
[doc.reference]`, which is also what lets the token post bytes.

Each file needs a sidecar `<file>.meta.yaml` with `date: YYYY-MM-DD`, its own date and not
today's, and may add `title` and `note`. A file without one stops the run and names the sidecar
to write. Dot-files and dot-directories are skipped.

The bytes go to Anam, never into Anam's directory: each batch names its files (`documents`:
`{path, file}`), and `anam_submit` posts each file's bytes to `POST /v1/documents?ext=` before
the envelopes, reading them from the file so no bytes ride in a ductile event. Anam names the
stored file by its sha256 (anam card 150) and answers 201 or 200 for bytes it now holds; the path
lends it only an extension. So a document rescanned under the same name is new bytes, and its
`doc.reference` supersedes the old one, whose bytes Anam keeps. Anam refuses a `doc.reference`
whose sha256 its library holds no bytes for.

```yaml
plugins:
  anam_documents:
    enabled: true
    config:
      documents_dir: <the documents folder, with sidecars>
      person_id: <Anam's person_id>
```

A `folder_watch` on the folder runs `handle`, and every run sends the whole folder as one
snapshot of `doc.reference`. `anam_submit` needs read access to the same folder.

## One-off exports: `records/extract`

An export that will never be sent again (a Fitbit Takeout, a Strong CSV, a Technogym zip, a
pathology PDF) gets no importer. A script in `records/extract` turns it into a records file
once, the file goes in the records folder, and `anam_records` sends it. Each script is
deterministic, so a rerun on the same export writes the same records and the resend is no-op.
Reshaping to a new Definition version is a rerun with the same ids, which supersedes in place.

| Script | Export | Records |
|---|---|---|
| `fitbit_weight.py` | Fitbit `Weight Logs.xlsx` | `health.weight` |
| `fitbit_sleep.py --zone Z` | Fitbit `Sleep Logs.xlsx` | `sleep.episode` (IEEE 1752) |
| `strong_csv.py --zone Z` | Strong app CSV | `exercise.session` (IEEE 1752) |
| `technogym_json.py` | Technogym mywellness zip, indoor sessions | `exercise.session` (IEEE 1752) |
| `acl_pathology.py` | Australian Clinical Labs report PDFs (needs `pdftotext`) | `lab.result`, `lab.panel` |
| `bp_diary_omh.py Z in out` | a records file's blood pressure rows | `health.blood-pressure` v4 (Open mHealth) |

`--zone` is the IANA zone the export's wall clock reads in. `strong_csv.py --max-session-sec`
(default 10800, 3 hours, the person's rule of 2026-10-08) caps a workout's duration, since Strong
keeps a workout open until the next one starts; another cap writes other records. The scripts moved from Anam's
`scripts/` (anam card 58) and write the same records; only `extracted.method` changed.

## Wiring an importer into a gateway (Garmin)

Not deployed, and not to be switched on alone. Source `garmin`, types
`[health.heart-rate-alert, exercise.session, sleep.episode, health.heart-rate-daily,
health.step-count, garmin.day]`, secret `anam_importer_token_garmin`, principal
`anam-submit-garmin`. Anam's `health-db` worker sends the same alerts today under source
`health-db`, and a facet's identity includes its source, so turning this on while that worker
runs would hold every alert twice. It goes live with the rest of anam card 55, when the
`health-db` facets retire.

It reads the monitoring FIT files GarminDB downloads (`FitFiles/Monitoring`) with Garmin's FIT
SDK, which its uv script header pins, and decodes FIT event 66, the abnormal high heart rate
alert, as the health ETL's `fit_events.py` does. It keeps no state: `handle` reads the files
modified in the last `lookback_days` (default 3), so a pipeline on GarminDB's sync event runs it;
`poll` reads every file and labels the run a snapshot.

Sleep comes from GarminDB's `garmin.db`, opened read-only: one `sleep.episode` per day its `sleep`
table holds a start for, as the IEEE 1752 `sleep-episode-1.0` body (time interval in UTC, the
stage durations in minutes) with Garmin's score, its word for it and the averages beside it.
Daily heart rate comes from the same file: each day's resting figure (`resting_hr`) and its
minimum and maximum (`daily_summary`), one `health.heart-rate-daily` facet each, as the Open
mHealth `heart-rate-2.0` body over the local day in Australia/Sydney. Steps are a
`health.step-count` per day (Open mHealth `step-count-3.0`), and the rest of `daily_summary` a
`garmin.day` as Garmin wrote it, so nothing the `health-db` summaries carried is lost. None of
these types is bundled in Anam, so the first batch of each makes `anam_submit` register it.

Sessions come from the activity FIT files GarminDB downloads (`FitFiles/Activities`), one
`exercise.session` per FIT session message, beside Technogym's and Strong's. The FIT file holds the
start as a true UTC instant; `garmin_activities.db` holds it as wall clock, and not always the same
wall clock, so the importer reads the file. The FIT sport and sub-sport map to Google Fit's names
(Cardio, which Google Fit has no name for, is `other`; an unmapped pair is `unknown`), and the
payload keeps both as the watch wrote them. `exercise.session` is bundled in Anam: the importer
carries Anam's v5 body unchanged, and `anam_submit` refuses to send until Anam publishes it.

Their ids name what they are: `garmin:session:2015-10-04T03:49:17Z`, `sleep:2015-10-08`, `steps:2015-10-09`, `day:2015-10-09`. A
facet's id is the source plus its identity values, without the type, so two types keyed on a
bare date would be one facet, the second superseding the first. `tests/conformance` pins the
IEEE and Open mHealth schemas the payloads are tested against. Read against GarminDB
3.6.7's schema; its 4.0 upgrade rebuilds the databases, so re-run the tests after it.

```yaml
plugins:
  anam_garmin:
    enabled: true
    timeouts:
      handle: 120s
      poll: 900s
    config:
      fit_dir: <GarminDB's FitFiles/Monitoring directory>
      activities_dir: <GarminDB's FitFiles/Activities directory>
      garmin_db: <GarminDB's DBs/garmin.db>
      person_id: <Anam's person_id>
```

Optional keys: `lookback_days` (default 3: a monitoring file covers a day and the watch syncs at
least daily) and `busy_timeout_ms` (default 30000: how long a read of `garmin.db` waits for
GarminDB's write before it asks to be retried). A bad value fails the command at start.

A file the SDK cannot decode is logged and skipped, and its run is then no snapshot; `health`
fails on it. Against a real archive of 7,738 files, `poll` found the same 302 alerts the ETL
holds, in 7 batches, 564 nights, 1,900 heart rate figures and 706 days of steps, every one passing its pinned schema. Its 199 activity files hold 200
sessions, all conforming; with the rest they were admitted to a scratch daemon, 4,076 facets, and a
resend was all no-op. Read over a network share it took 9 minutes (160 s of CPU).

## Wiring an importer into a gateway (Concept2)

Not deployed. Source `concept2`, type `[exercise.session]`, secret `anam_importer_token_concept2`,
principal `anam-submit-concept2`, and a second secret, the Logbook's own token, below.

ErgData syncs each workout the monitor records to the Concept2 Online Logbook, and its API
(`log.concept2.com/developers/documentation`) is where it reads back whole: the result, its
splits or intervals, and every stroke. A result entered by hand on the website is there too,
with totals only. The Google Fit copy ErgData also writes carries less and is on its way out, so
the importer reads the Logbook.

Two concerns, two commands. `fetch` is the source's reader: under a personal token (made on the
Logbook site under Edit Profile, Applications) it lists every result the user has, caches each
one that is new or changed as `<cache_dir>/<result id>.json` with its strokes, and drops the
cache of a result the Logbook no longer lists. It compares the listing to the cache, so an
unchanged result costs one listing call and nothing more, and it asks for strokes only where the
result says it has them. `handle` and `poll` shape what the cache holds and never touch the
network, as the garmin importer reads the files GarminDB downloaded: `handle` the files written
in the last `lookback_days` (default 3), `poll` everything, labelled a snapshot. The token is a
vault secret the gateway hands `fetch` under the name `token_secret` gives, never config.

Each workout is one `exercise.session`, the IEEE 1752 body with the Logbook's measures beside
it: `rower` is `rowing.machine`, `bike` is `biking.stationary`, `water` is `rowing`, any other erg
is `other`, and `erg_type` keeps the Logbook's word. The start is the result's `date_utc`, the
monitor's end of workout, minus its time; a result entered on the web has neither, so its start
is the day it names at Sydney midnight and `start_time_known` is false. The Logbook's tenths of
a second and decimetres are written in seconds and metres; a heart rate of zero, the monitor's
figure for no belt, is left out. `exercise.session` is bundled in Anam: the importer carries
Anam's v5 body unchanged, and `anam_submit` refuses to send until Anam publishes it.

```yaml
plugins:
  anam_concept2:
    enabled: true
    requires_vault: true                  # fetch needs the Logbook token
    vault_principal: anam-concept2        # the principal granted it
    timeouts:
      fetch: 300s
      handle: 60s
      poll: 120s
    schedules:
      - id: fetch
        command: fetch
        every: 6h
    config:
      cache_dir: <a folder of the importer's own>
      person_id: <Anam's person_id>
      token_secret: concept2_logbook_token
pipelines:
  - name: anam-concept2-after-fetch
    on: anam_concept2.fetched
    steps:
      - uses: anam_concept2             # handle: the results the fetch wrote
  - name: anam-concept2-submit
    on: anam_concept2.batch
    steps:
      - uses: anam_submit_concept2
```

Optional keys, each with its default: `logbook_url` (`https://log.concept2.com`), `logbook_user`
(`me`, the Logbook's name for the token's own user), `timeout` (30 seconds a call, connect to last
byte), `lookback_days` (3, the files a fetch can have written) and `max_response_bytes` (8 MiB: a
page of 250 results is under 1 MiB). A bad value fails every command at start, naming the key.

Against a real logbook of 19 results, 5 synced by ErgData (up to 752 strokes, 72 KB a payload) and
14 entered on the web, `fetch` took 10 s, every workout conformed, and all 19 were admitted to a
scratch daemon with a resend all no-op.

## Wiring an importer into a gateway (OwnTracks)

Not deployed. Source `owntracks`, type `[location.track]`, secret `anam_importer_token_owntracks`,
principal `anam-submit-owntracks`.

The phone runs OwnTracks in HTTP mode and posts each fix to a receiver at the edge, which keeps
it until the gateway's `owntracks` plugin (in ductile-plugins) pulls it into a spool:
`<spool_dir>/<device>/<YYYY-MM>.jsonl`, one line per message, the body exactly as the phone
posted it. The spool is the source. `anam_owntracks` reads it and never touches the network:
`handle` after a pull, `poll` for everything, labelled a snapshot.

Each phone's UTC hour is one `location.track`: the hour's fixes, oldest first, with the
coordinates, accuracy, speed, battery, WiFi network and regions the phone wrote, never snapped,
smoothed or joined to a place. The hour is the fix time's (`tst`), not the receipt's, so a phone
that was offline fills in its hours when it reconnects. A facet replaces the last one sent for its
hour, so an hour always goes whole: `handle` reads the whole spool and sends every hour that
gained a message received in the last `lookback_days` (default 2). OwnTracks reports one fix as
several messages with the same `tst` (a manual publish and a ping, or a ping repeating the last
fix every 15 minutes while the phone is still); they are one point, with every trigger kept. A
second message at the same `tst` with a different fix is dropped and counted. Messages that are
not locations (status, transition, waypoint) and empty posts are skipped and counted.

Optional keys: `lookback_days` (default 2) and `max_payload_bytes` (default 296960, 290 KiB:
Anam's gate takes a payload of up to 300 KiB, less room for the envelope). An hour over
`max_payload_bytes` is skipped and logged, and the run is then no snapshot; set it below your
Anam's own payload limit if that is not 300 KiB. A bad value fails the command at start.

No coordinates leave the payload. Logs and results carry counts, file names and line numbers,
because the gateway's logs are shipped elsewhere.

```yaml
plugins:
  anam_owntracks:
    enabled: true
    timeouts:
      handle: 60s
      poll: 120s
    config:
      spool_dir: <the owntracks plugin's spool_dir>
      person_id: <Anam's person_id>
pipelines:
  - name: anam-owntracks-after-pull
    on: location.new_data              # the owntracks plugin, when a pull found rows
    steps:
      - uses: anam_owntracks           # handle: the hours that gained messages
  - name: anam-owntracks-submit
    on: anam_owntracks.batch
    steps:
      - uses: anam_submit_owntracks
```

Against the live spool on its first day (18 lines: 16 locations, 1 status), `health` conformed
and `poll` shaped 2 points in one hour. The 16 locations were two fixes, one of them repeated by
15 pings over three hours while the phone sat still.

## Values: why `29.371`, not `29.371000000000002`

The withings plugin stores a measurement's value as a SQLite REAL, and a REAL has no text of
its own. Anam's Go worker reads it with `CAST(value AS TEXT)`, which its SQLite build renders
with 17 significant digits when 15 do not round-trip (`29.371000000000002`); SQLite 3.43 and
later render the shortest form (`29.371`). `anam_withings` writes the shortest decimal that
reads back as the same double (`repr`), which IEEE 754 fixes whatever reads it. Against the
live record that is 222 of 5,531 measurements written differently, each the same number.

## Licence

Apache License 2.0. See `LICENSE` and `NOTICE`.
