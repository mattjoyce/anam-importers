# Defaults and invariants

Every hard-coded value in anam-importers, sorted as anam card 151 sorts them (card 152, 2026-10-14).

- A **default** is a choice someone could reasonably make differently. It is a config key (or, for a
  one-off extractor, a flag), the constant stays as the shipped value, and `anam_importer.config`
  range-checks it at the start of each command, so a bad value fails there, naming the key.
- An **invariant** is a value whose change breaks data, identity or the contract with Anam or the
  source. It stays a constant, commented "Not configurable" where the reason is not already plain.

The range bounds in each check (3600 s, 3650 days, 600,000 ms, 1 GiB, 64 MiB) are sanity bounds on
what a person might type, not defaults. Line numbers are as of the card 152 branch.

## Defaults (config keys)

| Value | Where | Key | Why a default |
|---|---|---|---|
| 30 s | `anam_importer/client.py:22`, `anam_submit/run.py:52` | `timeout` (anam_submit) | how long a call may wait is the operator's trade between a slow Anam and a stuck gateway |
| 8 MiB | `anam_importer/client.py:27`, `anam_submit/run.py:53` | `max_response_bytes` (anam_submit) | a guard against a runaway answer; Anam's largest is under 1 MiB, so any value above that works |
| 20 | `anam_submit/run.py:35` | `absent_ids_shown` | how much of the absent list an alert carries is the reader's taste; bounded by Anam's 1,000 |
| 5000 ms | `withings/run.py:74` | `busy_timeout_ms` (withings) | how long to wait on the withings plugin's write before asking for a retry |
| `BloodPressure_*` | `bp_csv/run.py:48` | `pattern` | the app's file names; another app or a renamed export needs another glob |
| 3 days | `garmin/run.py:84` | `lookback_days` (garmin) | depends on how often the watch syncs |
| 30000 ms | `garmin/run.py:89` (was inline `timeout=30` in `query`) | `busy_timeout_ms` (garmin) | how long to wait on GarminDB's write |
| `https://log.concept2.com` | `concept2/run.py:55` | `logbook_url` | a test server or a proxy is a reasonable choice; now checked at load |
| `me` | `concept2/run.py:57` | `logbook_user` | the Logbook's name for the token's own user; another user id is valid |
| 30 s | `concept2/run.py:58` | `timeout` (concept2) | as for anam_submit |
| 3 days | `concept2/run.py:60` | `lookback_days` (concept2) | depends on the fetch schedule |
| 8 MiB | `concept2/run.py:63` | `max_response_bytes` (concept2) | a guard; a page of 250 results is under 1 MiB |
| 2 days | `owntracks/run.py:53` | `lookback_days` (owntracks) | depends on how long a phone may be offline |
| 290 KiB | `owntracks/run.py:59` | `max_payload_bytes` | follows Anam's payload limit, the daemon's `max_payload_bytes` (300 KiB by default since anam card 151); a daemon set to another limit needs another value here |
| 3 runs | `links/run.py` `DEFAULT_UNSEEN_AFTER` | `unseen_after` (links) | how long a person tolerates a file being missing before its facet says so is theirs: a synced folder wants more, a tidy one less |
| unset (assumption) | `bp_csv/run.py` `clock_of` | `zone` (bp_csv) | the zone a person says the cuff's clock is set to; set, `source_time` says configuration, unset, assumption (anam card 198). Only the Definition's zone is accepted until a fact can name its own zone |
| 3 hours | `records/extract/strong_csv.py:40` | `--max-session-sec` | the person's rule of 2026-10-08 for capping Strong's open-ended workouts; someone else's rule may differ |
| anthropic, openai, yubico | `purchase_gate/run.py` `DEFAULT_MERCHANTS` | `merchants` (purchase_gate) | which sellers may be filed unattended, with the pattern that finds each on the page and what a bare `$` means in its invoices, is the person's allow-list |
| 1,000,000 bytes | `purchase_gate/run.py` `DEFAULT_MAX_TEXT_BYTES` | `max_text_bytes` (purchase_gate) | the largest page text read; follows fabric's own default |
| 20 MiB | `purchase_gate/run.py` `DEFAULT_MAX_PDF_BYTES` | `max_pdf_bytes` (purchase_gate) | the largest PDF copied into the Library |

`timeout`, `busy_timeout_ms` (withings), `pattern`, `logbook_url`, `logbook_user` and every
`lookback_days` were keys before card 152; they are now range-checked at start and passed down as
parameters. `max_response_bytes`, `absent_ids_shown`, `busy_timeout_ms` (garmin),
`max_payload_bytes` and `--max-session-sec` are new. The test that changed the client's response cap
by setting a module global now passes `max_response` to `Client`, and a second test sets
`max_response_bytes` in anam_submit's config.

## Invariants

### Shared: `anam_importer`

| Value | Where | Why not configurable |
|---|---|---|
| `MAX_BATCH = 49` | `envelopes.py:13` | Anam refuses a larger batch (`gate.MaxBatch`), which card 151 kept an invariant: it decides which events share an anam-time |
| importers fill each batch to `MAX_BATCH` | every `batches(envs)` call | a smaller batch only means more transactions; borderline, see below |
| `run-<uuid4>` snapshot id | `envelopes.py:70` | Anam treats it as opaque; fresh per run is what makes a run one snapshot |
| first 5 problems in `Invalid` | `envelopes.py:20` | shapes an error message; the full list is on the exception |
| `OUTCOMES` | `client.py:35` | Anam's words for an envelope's fate (IMPORTERS.md §8) |
| `MAX_EXT = 16`, letters and digits | `client.py:40`, `:187` | Anam refuses another extension (`documentExt`); both sides must agree |
| `Anam-Timeout: <ms>ms`, at least 1 | `client.py:102` | the header's form Anam reads |
| 3xx is an error, never followed | `client.py:110` | following it would carry the token elsewhere |
| 5xx and 429 retry, other 4xx do not | `client.py:265` | what each status means in the contract |
| `READ_CHUNK = 65536` | `client.py:31` | a buffer size; the deadline and byte cap bound the read whatever it is |
| `ERROR_EXCERPT = 500`, `MALFORMED_EXCERPT = 200` | `client.py:233-234` | bound how much of a bad body an error quotes; a message, not behaviour |
| `/v1/...` paths, compact JSON body | `client.py:139-198`, `:172` | Anam's API |
| Draft 2020-12 validator, `verbatim` mode | `definitions.py:29-33` | Anam's manifest format |
| `"level": "info"`, protocol 2 shapes | `ductile.py:55` | the ductile protocol |
| range checks in `config.py` | `config.py` | the checks themselves |
| `BASES`, `OFFSET`, `WRITTEN_OFFSET` | `clock.py` | `source_time`'s vocabulary and its offset form, Anam's shape (anam card 197), and RFC 3339's offset |
| history as `definitions/history/<type>.v<n>.json`, sent oldest first | `definitions.py` `load` | Anam refuses a version older than one it holds (IMPORTERS.md §8.3) |

### anam_submit

| Value | Where | Why not configurable |
|---|---|---|
| `MAX_ABSENT_IDS = 1000` | `anam_submit/run.py:40` | The upper bound on `absent_ids_shown`, the size of an alert a person reads; the daemon's report holds `max_absent_ids`, 1000 by default (anam card 151) |
| events `anam.admitted`, `anam.snapshot_absent`, dedupe key `anam.snapshot_absent:<id>` | `run.py:99`, `:127-131` | pipelines route on them; a rename is a major release |
| `maxItems: 49` | `manifest.yaml:20` | `MAX_BATCH` |

### withings

| Value | Where | Why not configurable |
|---|---|---|
| `TYPE`, `BATCH_EVENT`, `withings.reconciled` | `withings/run.py:41-42`, `:173` | the Definition, the routed event, the withings plugin's event |
| `ATTRIB_AMBIGUOUS = "1"` | `:48` | what Withings' code means |
| `QUERY`, `FIELDS` | `:58`, `:68` | the source's schema and the payload the built-in worker wrote |
| `locked`/`busy` text means retry | `:93` | SQLite's words for a held lock |
| shortest round-trip decimal, no exponent | `render` | the Definition's value is a plain decimal; another rendering supersedes |
| `"health-check"` person | `:190` | a placeholder for validation; never sent |

### bp_csv

| Value | Where | Why not configurable |
|---|---|---|
| `ZONE` | `bp_csv/run.py` | read from the Definition's `fact_time.zone`; the `zone` key may only confirm it, since the Definition places the reading there |
| `POSTURES` | `:193` | Open mHealth's vocabulary; a change rewrites facets |
| `%Y-%m-%d %H:%M:%S`, `%d-%B-%Y`, `mmHg` | `:201`, `:226`, `:203-204` | the app's formats and OMH's unit |
| Go `encoding/csv` splitting, UTF-8 with replacement | `records()`, `:151` | how the built-in worker read it, so the same row is the same facet |

### dreamstation_card

| Value | Where | Why not configurable |
|---|---|---|
| `TYPE`, `BATCH_EVENT`, `KEPT` | `dreamstation_card/run.py:38-44` | the Definition decides what a session holds |
| first 5 skipped files in `health` | `:127` | shapes a message |
| decoder pinned to `v0.1.0` | script header | a dependency pin, changed by a release |

### records

| Value | Where | Why not configurable |
|---|---|---|
| `FIELDS` | `records/run.py:53` | the worker's strict top level |
| `IDENTITY` | `:60` | restates Anam's bundled `health.blood-pressure` identity key; the importer carries no Definition and does not fetch one before it scans, so reading it is not cheap |
| `_NULLS`, `_BOOLS`, `_SPECIAL_FLOATS`, `_YAML_FLOAT`, `_DOT_FLOAT`, `_INT64` | `:73-79` | Go yaml.v3's resolution, so a record is the same facet |
| `1e-6`, `1e21` | `:127` | Go `encoding/json`'s float rendering |
| `.yaml`, `.yml`, `.json` | `:258` | what the worker read; the snapshot is that set |
| `"health-check"` person | `:301` | validation placeholder |

### documents

| Value | Where | Why not configurable |
|---|---|---|
| `SIDECAR = ".meta.yaml"`, `MEASURED` | `documents/run.py:62-63` | the worker's name, which every sidecar follows; the Definition's measured fields |
| `ZONE = "Australia/Sydney"` | `documents/run.py` | where `record.document`'s Definition reads a sidecar's date; another zone would make `source_time` deny the fact time (anam card 198) |
| the media type table, `application/octet-stream` | `media_type` | another spelling supersedes every reference |
| dot-files, dot-directories and symlinks skipped | `:134-137` | the worker's walk; a change alters the snapshot |
| 1 MiB hash chunk | `:151` | a buffer size |

### links

| Value | Where | Why not configurable |
|---|---|---|
| `TYPE`, `BATCH_EVENT`, `MODES`, `SOURCES` | `links/run.py` | the Definition's vocabulary and the routed event; the id prefixes are part of identity |
| `MARKDOWN`, `EXIF_KINDS` | `links/run.py` | which files have frontmatter read and mtime refused, and which have EXIF read: what the Definition's `date_from` means |
| `FRONT_READ = 64 KiB`, `EXIF_READ = 1 MiB`, 1 MiB hash chunk | `links/run.py` | buffer sizes; a frontmatter or an IFD past them is not read, which a bound must say |
| `FILENAME_DATE` | `links/run.py` | the `YYYY-MM-DD` prefix the Definition names; another pattern moves fact-times |
| `STATE_VERSION = 1` | `links/run.py` | the state file's shape |
| the media type table | `media_type` | as documents: another spelling supersedes every link |
| dot-files, dot-directories and symlinks skipped | `files` | the walk; a change alters the snapshot |
| `state_file` has no default and may not sit under `links_dir` | `settings` | an importer reads its source and does not write into it; a required key, not a default |

### garmin

| Value | Where | Why not configurable |
|---|---|---|
| the seven type names, `BATCH_EVENT` | `garmin/run.py:52-65`, `:89` | Definitions and the routed event |
| `DAY_COLUMNS`, `DAY_MINUTES`, `DAY_GOALS` | `:74-82` | GarminDB's schema and the Definition's fields |
| `ZONE` | `:87` | read from the Definition already; used only for a day Garmin gave no interval for |
| `HR_HIGH_ALERT = 66`, `data >> 8`, `& 0xFF` | `:92`, `:126` | what the watch writes |
| `FIT_EPOCH`, `WIDE`, `HALF` | `:98-99` | the FIT format's epoch and the width of a monitoring message's short timestamp |
| `MINUTES = 60` | `:103` | the hour facet's slots, one a minute: the payload's shape |
| `ACTIVITY_NAMES`, `SESSION_MEASURES`, `SESSION_UNITS`, `"unknown"` | `:261-302`, `:272` | the payload's vocabulary; a change supersedes every session |
| id prefixes `garmin:session:`, `sleep:`, `steps:`, `day:`; `"source": "garmin"` | `:142`, `:394`, `:580`, `:689`, `:698` | identity |
| `is_main_sleep: true` | `:589` | the Definition records that Garmin's table holds the main sleep |
| `*.fit` | `:230` | the format |
| `MAX_OFFSET` | `:441` | the widest offset any zone keeps |
| `WELLNESS`, `SLEEP_CLOCKS`, `daily_summary_<day>.json` under the year, `sleep_<day>.json` | `:479`, `:552` | Garmin Connect's JSON as GarminDB 3.6.7 keeps it |
| `since` minus one day for `garmin.db` | `:784` | covers the local day holding the cutoff; follows `lookback_days` |
| 86400 | `:780` | seconds in a day |

### concept2

| Value | Where | Why not configurable |
|---|---|---|
| `SESSION_TYPE`, `BATCH_EVENT`, `FETCHED_EVENT` | `concept2/run.py:48-50` | the Definition and routed events |
| `PAGE = 250` | `:67` | the API's maximum; smaller is only more calls (borderline) |
| `ACCEPT` | `:70` | pins the API version `session()` reads |
| `READ_CHUNK`, `ERROR_EXCERPT` | `:73-76` | a buffer size; a message's length |
| `ZONE` | `:101` | read from the Definition already |
| `ERG_NAMES`, `"other"`, `HEART_RATES`, `SPLIT_HEART_RATES` | `:106-112`, `:197` | the payload's vocabulary |
| tenths and decimetres, zero heart rate means none | `tenths`, `positive` | the Logbook's units |
| `concept2:session:<id>`, `"Concept2 Logbook"` | `:196`, `:200` | identity and payload |
| 3xx refused; 5xx and 429 retry | `:273`, `:299` | the token stays with the Logbook; what the statuses mean |
| `.tmp` beside the cache file | `:360` | how a write is made whole |

### owntracks

| Value | Where | Why not configurable |
|---|---|---|
| `TRACK_TYPE`, `BATCH_EVENT` | `owntracks/run.py:46-47` | Definition and routed event |
| `FIELDS`, `NUMBERS`, `INTEGERS`, `STRINGS`, `TRANSPORT` | `:78-87` | the Definition's names and OwnTracks' body |
| `FIX_KEYS` | `:92` | decides which points an hour's facet holds |
| one UTC hour (`tst % 3600`), `loc:<device>:<hour>` | `:110`, `:169` | identity |
| lat and lon ranges, `batt` 0..100, `bs` 0..3, negative accuracy means unknown | `:120-138` | OwnTracks' value ranges |
| `*/*.jsonl` | `:205` | the owntracks plugin's spool layout |

### records/extract (one-off scripts)

| Value | Where | Why not configurable |
|---|---|---|
| `METHOD`, `VERSION`, `extracted.version` | each script | provenance |
| `yaml.safe_dump(width=100)`, file name `<sha256[:12]>` | each script | a rerun writes the same file |
| `TERMINATORS`, `SECTION_WORDS`, `VALUE_RE`, `RANGE_RE` | `acl_pathology.py:38-44` | the lab report's layout |
| two-digit year is 20yy; unknown time `00:00` with `time_unknown` | `acl_pathology.py:60`, `:301` | the reports' dates; the flag records the gap |
| `ZONE = "Australia/Sydney"` | `acl_pathology.py` | where the lab types' Definitions read `collected`; the reports print no zone, so it is an assumption (anam card 198) |
| `LAYOUT` | `fitbit_sleep.py:38` | Fitbit's format |
| `;` delimiter | `strong_csv.py:57` | Strong's format |
| `IEEE`, `EXTRA`, `IGNORED`, `SPLIT`, `ORDER`; round to the second | `technogym_json.py:30-53`, `:84` | the payload's vocabulary; a deterministic start |
| `POSTURES`, `mmHg` | `bp_diary_omh.py:34`, `:49-51` | as bp_csv |

## Borderline, for review

- **Batch size below 49.** Importers always fill batches to `MAX_BATCH`. A smaller size would cut a
  batch event's bytes (a Concept2 batch with strokes can reach a few MB), so it could be a
  `batch_size` key on every importer. Left as is; flipping it touches every manifest.
- **`PAGE = 250`** (concept2). The API's maximum. Sorted invariant because a smaller page only adds
  calls.
- **Buffer sizes and error excerpt lengths.** Sorted invariant because they change no outcome. They
  are not what card 151 calls an invariant (nothing breaks if changed); they are left as constants
  because a key for them would be noise.
- **`.meta.yaml`** and the records suffixes. Taste in principle, but every existing sidecar and
  records file follows them, and a change would alter what a snapshot holds.
- **`IDENTITY`** in records restates a Definition. Reading it from Anam's `/v1/definitions` would
  need a call the importer does not make today.

### `purchase_gate`

| Value | Where | Why not configurable |
|---|---|---|
| `GATE_VERSION` | `purchase_gate/run.py` | this file's version, written into every filed record's `basis`; it is the manifest's |
| slug, ref, date and currency patterns | `purchase_gate/run.py` | restate the `money.purchase` Definition and the file names the importers read |
| `CURRENCIES`, `SYMBOLS` | `purchase_gate/run.py` | ISO 4217 codes the gate can vouch for, and symbols that mean one currency whatever the merchant; a bare `$` is the merchant's (`merchants`) |
| `KIND_WORDS`, `REF_WORDS` | `purchase_gate/run.py` | the words that make a line a subtotal, shipping, tax or total line, and a ref an invoice, receipt or order number: the check itself |
| `MAX_SNIPPET = 400` | `purchase_gate/run.py` | a snippet is a line of a page, not the page |

