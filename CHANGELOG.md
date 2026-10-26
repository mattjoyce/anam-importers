# Changelog

All notable changes to this repo. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the repo follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): one version for the base,
`anam_submit` and every importer, kept in `VERSION` and in each plugin manifest.

## [Unreleased]

### Changed

- `purchase_gate`: a PDF whose exact bytes are already in `documents/` is `already_filed`, whatever its
  sidecar or record says. A replay over 0.1.0's filings had filed a second copy under a mail name,
  because 0.1.0's sidecar note differs from 0.2.0's.
- `purchase_gate` files every forwarded mail (anam card 242, Matt 2026-10-27) and no longer holds. The PDF
  and its sidecar always go into `documents/`. A failed optional value (order or receipt ref, subtotal,
  shipping, tax, items) is dropped and named; the sums run only when every part survived, and when they
  disagree the parts go and the total stands. A failed required value (date, total, currency, merchant, one
  checked ref) files the PDF as a document only, named `<received date>_mail_<key>_<stem>` with the mail's
  subject as its title. The same purchase forwarded again is `already_filed`; a taken document name gets
  a sha256 suffix. Each PDF gets `attachments/<pdf>.result.json` (status, files, dropped, missing) in place of
  the per-message `result.json` and `hold.json`. Anthropic's allow-list entry also accepts the 2024 issuer
  line `Anthropic` above the `Bill to` column. Gate version 0.2.0.
- `agentmail` no longer runs `pdftotext` (anam card 250). The poll spools the PDF and emits `agentmail.pdf`
  with `{payload_dir, pdf}`; `message.json` no longer names a `text` file; health no longer asks for
  `pdftotext`. The `pdf_text` plugin in ductile-plugins writes `<pdf>.txt` as the next pipeline step, so
  the gate's `input_file` check is unchanged. The image needs no poppler for the poll.

### Added

- `purchase_gate` takes `filing_subdir`, and `anam_records` takes `subdirs` (anam card 242): on a gateway
  that mounts the Library read-only, the gate files into `documents/mail` and `records/mail` alone, and the
  records importer reads `records/mail` into the same snapshot as `records/`.
- `purchase_gate/` and `patterns/extract_purchase` (anam card 242): the last step of the invoice chain. A
  fabric pattern asks a model to transcribe an invoice with the text each value was read from; the gate
  files a PDF, its sidecar and a `money.purchase` in the Library only when the page text proves the
  proposal (evidence on one line, currency beside the total, refs after their own label, the sums, an
  allow-listed issuer), and otherwise writes `hold.json` with every reason. It never overwrites a file.
- `agentmail/` is a Ductile plugin (anam card 242, slice two): `poll` spools each message of an AgentMail
  inbox as a folder under `mail_spool` (`message.json` with AgentMail's SPF, DKIM and DMARC results as
  given, the attachments byte-exact, a `pdftotext -layout` `.txt` beside each PDF), built under a
  temporary name and renamed into place, and emits one `agentmail.pdf` event per PDF newly spooled.
  A message with a failing attachment is not spooled and is retried next poll. `health` checks the key,
  the folder and `pdftotext`. The key is the vault secret `key_secret` names
  (`agentmail_api_key` by default; Ductile's vault names are lowercase).
- `agentmail/fetch.py` copies an AgentMail inbox's attachments into a spool folder, byte-exact, with a
  `manifest.csv` (anam card 242). Slice one: it sends nothing to Anam.
- `records/extract/add_source_time.py` (anam card 198): gives every record of `health.weight`,
  `health.lab-result`, `health.lab-panel`, `health.blood-pressure`, `health.encounter` and
  `health.donation` the `source_time` block their Definitions now require, in a staging folder and
  never in the records folder. The block states `Australia/Sydney` with `basis: source` and, for
  weight, the offset the date had; a wall clock Sydney skips or repeats stops the run and is listed.
  The change is textual, so a diff against the original is the added lines alone, and `--verify`
  checks a staged folder against its originals and their recorded hashes.
- `garmin/` sends an hour's heart rate (anam card 129): `health.heart-rate.hour`, one facet a UTC
  hour that has a sample, read from the watch's monitoring FIT files beside the alert. A payload
  is 60 slots, slot *i* minute *i*, each the watch's reading in that minute or `null` for one it
  recorded none; nothing is averaged and no bucket is kept. A monitoring message's 16-bit short
  timestamp is placed by the last full one in its file, and a sample that cannot be placed is
  logged and makes the run no snapshot. `poll`'s snapshot names the type, so the garmin principal
  must list it.

- `links/` (`anam_links`): a folder of files as `record.link`, a file Anam remembers but does not
  hold (anam card 165). Each file's name, hash, size, media type and date are sent and the bytes
  never are; one instance is one folder under one identity mode (`path`, `content` or `id`),
  which the `id` carries as its prefix. Fact-time is the first of frontmatter `date`, EXIF
  `DateTimeOriginal`, a `YYYY-MM-DD` file-name prefix and mtime, read in the instance's `zone`
  when it has no offset. A file missing for `unseen_after` complete runs is superseded with
  `unseen: true`, never retracted, and comes back by another supersession; the count is the
  importer's, in `state_file`. The importer registers `record.link` with a `handling` block.

- `docs/explainer/`: an explainer bundle (102 concepts) with `check.py`, which verifies every
  resource, anchor, symbol and test the bundle names against the tracked files, and `render.py`,
  which renders it to one `explainer.html`. Both use only the standard library.

- `scripts/rebuild-drill.py` builds a fresh ledger from the importers alone and compares it with
  the live record, type by type (anam card 141). `docs/rebuild-drill.md` says how to run it.

### Changed

- `bp_csv/` carries `health.blood-pressure` v8 (anam card 198), which requires `source_time`; the
  importer already sent it, so only the Definition's copy moves. `acl_pathology.py` writes
  `basis: source` where it wrote `assumption`, and `fitbit_weight.py` writes `source_time` with the
  offset for each log time, since the records files state the zone. These deploy with anam's
  `health.weight` v7, `health.lab-result` v3, `health.lab-panel` v3 and `health.blood-pressure` v8,
  and with the records folder swapped for the staged one, never before.
- Garmin's `poll` snapshot no longer names `health.heart-rate-day` (anam card 208): `RETIRED_TYPES`
  in `garmin/run.py` is empty, because the live retraction of the old three-a-day facts has run.
  The mechanism stays for the next retired type. The daemon refuses a snapshot type its principal
  does not list, so the garmin principal's `types` keeps `health.heart-rate-day` until this
  importer is deployed.

- Garmin sends one `health.heart-rate.day` a day, its resting, minimum and maximum heart rate
  as fields, in place of three `health.heart-rate-day` facts a day (anam card 205). A figure Garmin
  left empty is a field the day does not carry; a day assumed because Garmin gave no interval
  (18 February 2026) still says so. `poll`'s snapshot also names `health.heart-rate-day` with
  nothing of it carried, so the old facts are reported absent and `anam retract garmin`
  tombstones them; the garmin principal keeps listing that type while the importer names it.

- Every importer says how its clock was read (anam card 198). Each payload carries `source_time`
  (`value` as the source gave it, the `zone` it is read in, and `basis`: source, configuration or
  assumption). bp_csv reads `date_excel` in a new `zone` key (configuration) or the Definition's
  zone (assumption, logged); the key may name only that zone until a fact can name its own, and an
  undated export's mtime is read in it, never the host's zone. withings: `date`, UTC; the device's
  `timezone` stays in its field. concept2: `date_utc`, UTC, or a web entry's date at midnight in
  the Logbook's `timezone` for it (source) or Sydney (assumption, logged). documents: the sidecar's
  date in Sydney (assumption, logged), and a sidecar may not declare `source_time`. links: by
  `date_from`, and a file remembered from before keeps its date's offset as an assumption.
  dreamstation_card, owntracks and stays: UTC epochs. `fitbit_sleep.py`, `strong_csv.py`,
  `technogym_json.py` and `acl_pathology.py` write it too (extraction versions 3, 3, 3 and 2).
  Wall clocks are read by `clock.local_instant`, so one a zone skips or repeats is left out with a
  log line (an importer's run is then no snapshot) or stops an extractor, never guessed.
  New versions: `health.measurement.withings`, `health.cpap-session.dreamstation`, `place.track`,
  `place.stay` and `record.link` v2, each requiring `source_time`, the v1 bodies kept in
  `definitions/history/`; `health.blood-pressure` v7 and `activity.exercise-session.concept2` v2
  are Anam's bundled bodies, byte for byte. Deploy anam first.

- `anam_importer.load` reads `definitions/history/<type>.v<n>.json` for the types an importer
  emits now, and every batch carries every version, each type's oldest first, so a rebuilt
  operational store holds every version an importer emitted (IMPORTERS.md §8.3). History under an
  old name is not sent. `load` returns `Definitions`, a dict of the current ones with `every` and
  `manifests()`.

- Vendor-shaped types take the vendor leaf (anam card 195). garmin sends
  `activity.exercise-session.garmin` and `activity.day.garmin`, concept2
  `activity.exercise-session.concept2`, withings `health.measurement.withings` and dreamstation_card
  `health.cpap-session.dreamstation`; `technogym_json.py` and `strong_csv.py` write
  `activity.exercise-session.technogym` and `.strong`. The two exercise leaves are byte copies of
  Anam's bundled bodies; the three registered leaves are v1, their old type's body under the new
  name, the old body kept in `definitions/history/`. `activity.day.garmin` reads its fact time at
  the start of the day Garmin counted, where `activity.day` read the date at Sydney midnight.
  `retype_records.py` takes a table's select rows, retypes only a record's own `type`, and refuses
  a record of a split type that no one row places; the records files on the Library share are
  retyped with `--table renames/vendor-leaves.json` from anam after its rename run.

- The medication, illness and trip types take a third segment (anam card 196):
  `health.medication-started` is `health.medication.started`, and likewise `.stopped`, `.dose`,
  `.dose-changed`, `.compliance`; `health.medication-missed-dose` is
  `health.medication.dose-missed`; `health.illness-started` and `-ended` are
  `health.illness.started` and `.ended`; `place.departed`, `.arrived`, `.returned` and `.flight`
  are `place.trip.departed` and so on. The records files on the Library share are retyped with
  `retype_records.py --table renames/kinds-segment.json` from anam, after its rename run has
  carried the live facets over.

- `record.note` is `record.edge` (anam card 191). The records files on the Library share are
  retyped with `retype_records.py --table renames/record-edge.json` from anam, after its rename run
  has carried the notes over; `about` stays as written, since `record.edge` accepts it as the old
  name of `to`.

- The taxonomy (anam card 147). Every type is named `domain.concept` under one of eight domains,
  and each importer names the new ones: garmin sends `activity.day` (was `garmin.day`),
  `activity.exercise-session`, `activity.steps`, `health.heart-rate-day` (was
  `health.heart-rate-daily`), `health.sleep-episode` (was `sleep.episode`) and
  `health.heart-rate-alert` v4; concept2 `activity.exercise-session`; dreamstation
  `health.cpap-session`; owntracks `place.track`; stays `place.stay`; documents `record.document`
  (was `doc.reference`); withings `health.measurement` v4; bp_csv `health.blood-pressure` v6. Every
  Definition declares `kind` and `family`; the copies of core's bundled types are core's files, byte
  for byte. A renamed type starts at v1 under its new name. `records/extract/retype_records.py`
  rewrites the `type:` of the records files on the Library share from anam's
  `renames/taxonomy.json`, dry by default. Needs an Anam with card 147, after its rename run has
  carried the record over: the old names are no longer admitted there, and the new ones are
  refused by an Anam without it.

- `Client.store_document` posts `POST /v1/documents?ext=` with the name's extension, not a path
  (anam card 150). Anam names the stored file by its sha256, so there is no 409: a document
  rescanned under the same name supersedes its reference, and the first bytes stay. Needs an Anam
  with card 150.

- Every config key is read and range-checked at the start of a command, through
  `anam_importer.config`, and passed down as a parameter (anam cards 151, 152). A value of the
  wrong kind or out of range now fails the command at start, naming the key, where before some
  failed late or not at all. Defaults are unchanged. `bp_csv` reads its zone from its Definition.
  `docs/defaults-and-invariants.md` lists every hard-coded value and why it is a key or a constant.
- The explainer's Definition manifest page lists all twelve types in thirteen files with their
  current versions, `family` and `kind`, and its bp_csv, Withings and Concept2 pages name the
  versions now in force. The records section of the README names the new medication, illness and
  trip types in place of `med.*`, `illness.*` and `travel.*`. The explainer log has an entry for
  cards 147, 165 and 174 (anam card 147).

### Fixed

- `bp_csv`: an export dropped in the watched folder is read. folder_watch reports the file's path
  relative to the watch's root, and `handle` read the bare name, so every drop failed with "no export
  at" and only a full poll brought readings in. `handle` now reads the path under the event's `root`,
  or under `export_dir` when the event has none.

- The rebuild drill's records fixture says how the note's clock was read, so the drill passes
  against a daemon built from anam master. `record.edge` v2 requires `source_time` and reads its
  offset, so the note in the fixture was refused for a missing `source_time` and the whole batch
  with it. The note now carries the wall clock as it was written, the zone it was written in and
  the offset that zone kept then.

- `garmin`: a `sleep.episode`'s start and end are now true UTC instants (anam card 174). GarminDB
  stores them as naive wall clock in its process's zone, and that process runs in the days' zone
  (Australia/Sydney), so the importer stamped Sydney wall clock with `Z` and every night sat 10 to
  11 hours late. The ids and the Definition are unchanged; a `poll` resends every night with the
  corrected instants and each facet supersedes.

- The README's "Wiring an importer into a gateway" sections say which importers are live on the unraid
  gateway, and since when, in place of "Not deployed". The Withings section no longer says the
  built-in worker still runs, and Garmin's no longer says `health-db` does.

### Added

- Config keys for values that were fixed (anam card 152), each defaulting to the old value:
  `anam_submit`'s `max_response_bytes` (8 MiB) and `absent_ids_shown` (20); `anam_garmin`'s
  `busy_timeout_ms` (30000); `anam_concept2`'s `max_response_bytes` (8 MiB); `anam_owntracks`'s
  `max_payload_bytes` (290 KiB); and `strong_csv.py --max-session-sec` (3 hours). `Client` takes
  `max_response`.

- `ANAM_SEED_BIN` for the tests against a real daemon (anam card 119). The takeover tests seed
  their ledger with the built-in workers' `anam ingest`, which Anam drops in card 119; with
  `ANAM_SEED_BIN` naming a build from before it and `ANAM_BIN` one from after, the test runs the
  cut-over itself. A seeding build with no `ingest` skips those tests and says why.

- `anam_documents` (anam card 103), under source `documents`: Anam's built-in documents worker,
  moved out. A folder of files with `.meta.yaml` sidecars as `doc.reference`, with the same
  payload the worker wrote, so the cut-over is no-op. `anam_submit` hands each file's bytes to
  Anam's library (`POST /v1/documents`, anam card 102) before the envelopes, reading them from
  the file named in the batch's `documents`; `Client.store_document` does the post.

- `anam_owntracks` (anam card 130), under source `owntracks`: the positions a phone's OwnTracks
  posted, from the spool the ductile `owntracks` plugin pulls, as `location.track` v1, one facet
  per phone per UTC hour. Messages for one fix (same `tst`) are one point with every trigger;
  `handle` sends each hour that gained a message whole. Logs carry no coordinates.

- `anam_concept2` (anam card 122), under source `concept2`: each workout the Concept2 Logbook
  holds as `exercise.session` v5, splits or intervals and every stroke beside the IEEE 1752 body.
  `fetch` reads the Logbook API under a personal token from the vault and caches each result as
  a JSON file; `handle` and `poll` shape the cache and never touch the network. `anam_garmin`
  carries the same v5 body.

- `records/extract` (anam card 58): the one-off extractors moved out of Anam's `scripts/`
  (Fitbit weights, Strong, Technogym indoor sessions, pathology PDFs, the blood pressure diary
  reshape). On the same exports they write the same records. The zone a script reads a wall
  clock in is now `--zone`, not a constant.
- `records/extract/fitbit_sleep.py`: Fitbit's `Sleep Logs.xlsx` as `sleep.episode` records, ids
  `fitbit:sleep:<local start>`. Only the columns whose arithmetic proves them are read.
- `anam_records` (anam card 118): Anam's built-in records worker, moved out. It reads YAML and
  JSON records files with Go's yaml.v3 scalar rules and writes numbers as Go wrote them, so
  every record the worker admitted resends as no-op. Every run is one snapshot of the types it
  carries.
- `anam_submit` stamps each type's current version on the envelopes of a batch that sets
  `current_versions` and names none. Any other envelope without a version is still refused.

- `anam_garmin` (anam card 55), under source `garmin`, from GarminDB's FIT files and `garmin.db`:
  - `health.heart-rate-alert` v3, the abnormal high heart rate alert decoded from the monitoring
    FIT files: the health ETL's `fit_events.py`, moved, with the payload Anam's `health-db` worker
    builds today.
  - `sleep.episode` v1, one per night: the IEEE 1752 `sleep-episode-1.0` body with Garmin's score,
    qualifier and averages beside it.
  - `health.heart-rate-daily` v1: each day's resting, minimum and maximum heart rate, one facet
    each, as the Open mHealth `heart-rate-2.0` body over the local day.
  - `health.step-count` v1, the Open mHealth `step-count-3.0` body, and `garmin.day` v1, the rest
    of `daily_summary` as Garmin wrote it.

  Ids name what they are (`sleep:`, `steps:`, `day:`): a facet's id is the source plus its
  identity values, without the type, so two types keyed on a bare date would be one facet. The
  new types are registered through the API; `tests/conformance` pins the IEEE and Open mHealth
  schemas the payloads are tested against. Not to be enabled before the `health-db` facets retire.
- `anam_bp_csv` emits `health.blood-pressure` v5 (anam card 97): the six columns the app can fill
  that v4 did not name (irregular heartbeat, dizzy / light-headed, temperature, blood glucose,
  oxygen saturation, tags), kept as the export's text. Under v4 one ticked checkbox stopped that
  export and every later one. Needs the Anam release with v5.

- `anam_bp_csv` emits `health.blood-pressure` v4 (anam card 83): the Open mHealth
  `blood-pressure-4.0` body, systolic and diastolic as numbers in mmHg and the time with Sydney's
  offset, with `date_excel`, `reading` and the export's other fields beside it as written. The
  app's `Seated` is `sitting`; an unknown posture stops the run. Needs the Anam release with v4.

- Snapshots (anam card 78): every resend-everything run labels its batches as one snapshot, and
  `anam_submit` raises `anam.snapshot_absent` when the part that completes it finds facets Anam
  holds live that the run did not carry. Nothing is retracted automatically. Needs Anam a14ee51
  or later. `anam_importer.snapshot_parts` labels a run; `ductile.event` takes a `dedupe_key`.

- `anam_dreamstation`, the CPAP importer: a Philips DreamStation SD card copy as
  `sleep.cpap-session` v1, one facet per therapy session, holding only what the device wrote
  (times, mask-on spans, settings, its pressure summary and counts, a tally of the events
  file). Its Definition is registered through the API. Needs the `dreamstation` decoder.
- `anam_bp_csv`, the blood pressure importer: a phone app export (`BloodPressure_<date>`) as
  `health.blood-pressure` v2, the built-in `bpcsv` worker's reading moved, so the same export
  through either is the same facets. Runs on a `folder_watch` per-file event; `poll` resends
  every export under `export_dir`.

### Changed

- `anam_bp_csv` emits `health.blood-pressure` v3, the body Anam bundles from its card 71
  (descriptions and examples added, no contract change). It needs an Anam with that release:
  an older one refuses v3 as a bundled type it does not hold, and the new one refuses v2 as not
  current, so the importer and Anam deploy together.

- `anam_submit` reads its token from the vault secret its instance config names in
  `token_secret`, a new required key, instead of a fixed `ANAM_IMPORTER_TOKEN`. Vault secret
  names are lowercase and global, so one fixed name could not serve two importers. For
  Withings: `token_secret: anam_importer_token_withings`.

### Fixed

- The client never follows a redirect (anam card 112). It used urllib's default handler, which
  sent the importer's bearer token to whatever origin a 3xx named. A redirect is now an error
  naming the target, and `anam_url` may not carry credentials, a query or a fragment.
- `anam_submit` acknowledges a batch only on a whole admission receipt (anam card 113): W, the
  change count, and a known outcome for every index. A 200 holding anything else, an HTML page
  or `{}`, was reported ok with an `anam.admitted` event; now it is a retryable error and no
  event. The Definitions listing, a registration and a snapshot report are checked the same way.
- A truncated answer is retryable (anam card 115). The batch may or may not have been written,
  and a resend settles which.
- `timeout` bounds the whole call (anam card 116): connect, headers and body, with answers capped
  at 8 MiB. A server trickling bytes held the worker past it. `Anam-Timeout` keeps fractions
  (`250ms`, not `0s`).
- `anam_bp_csv` refuses an export whose records cannot be told apart (anam card 114): a quote
  still open at the end, a quote inside a quoted field that neither closes nor doubles it, or a
  record with another field count than the header. Under the worker's LazyQuotes, a comment that
  lost its closing quote swallowed the next reading and a poll still claimed a complete snapshot,
  so Anam reported that reading absent. Padded fields, doubled quotes and closed multi-line
  fields still read; the real export of 11 July has none of the refused shapes.
- A request that is JSON but not an object gets a structured error, not a traceback (anam card
  117).

- `anam_bp_csv` sends exports oldest first by the date in their name, not in path-string order,
  and sends a reading two exports hold once, from the newer (anam card 98). Before, the 9th's
  export sorted after the 10th's, so a resend put an older comment back over a correction.
- `anam_dreamstation` labels no snapshot when the card holds an events file without its summary
  (anam card 99): the run cannot carry that session, so Anam must not be told it is absent.

- `anam_dreamstation` fetches the decoder as the tag's zip archive, not `git+https`: the gateway
  has no git, so uv could not resolve it.

- The README's gateway examples set `timeouts:` per command. A flat `timeout:` is not a ductile
  plugin field: `config check` passes it, and the gateway then crash-loops at boot.

## [0.1.0] - 2026-10-10

First release. Needs an Anam daemon with the importer routes (anam card 53).

### Added

- `anam_importer`, the shared base: load an importer's Definitions from its folder, validate
  each payload locally with JSON Schema 2020-12, cut batches of 49, publish Definitions
  (GET before register), submit, and speak the ductile plugin protocol v2.
- `anam_submit`, the ductile plugin that posts one batch under one importer's token. A
  refused batch is reported and not retried; a 503 or a network failure is retried.
- `anam_withings`, the Withings importer: the withings plugin's measurements as
  `health.measurement` v3, one group on `withings.measurement_recorded`, everything on
  `withings.reconciled` or `poll`.
- Tests against a real Anam daemon when `ANAM_BIN` names one.
- `docs/explainer.html`, how the pieces fit.

### Fixed (before release, from review)

- A measurement's value is the shortest decimal that reads back as the same double, written
  without an exponent: `0.00001`, not `1e-05`, which the Definition refuses.
- A pipeline step runs `handle`, so `handle` resends everything on `withings.reconciled`.
- A database failure is a protocol error with its retry: a locked database is retried, a
  missing table is not, and no failure leaves stdout empty.
- The README's gateway example puts `max_attempts` under `retry:` and schedules a daily resend.

[Unreleased]: https://github.com/mattjoyce/anam-importers/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/mattjoyce/anam-importers/releases/tag/v0.1.0
