# Changelog

All notable changes to this repo. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the repo follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): one version for the base,
`anam_submit` and every importer, kept in `VERSION` and in each plugin manifest.

## [Unreleased]

### Added

- `anam_records` (anam card 118): Anam's built-in records worker, moved out. It reads YAML and
  JSON records files with Go's yaml.v3 scalar rules and writes numbers as Go wrote them, so
  every record the worker admitted resends as no-op. Every run is one snapshot of the types it
  carries.
- `anam_submit` stamps each type's current version on the envelopes of a batch that sets
  `current_versions` and names none. Any other envelope without a version is still refused.

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
- A request that is JSON but not an object gets a structured error, not a traceback (anam card
  117).

- `anam_bp_csv` sends exports oldest first by the date in their name, not in path-string order,
  and sends a reading two exports hold once, from the newer (anam card 98). Before, the 9th's
  export sorted after the 10th's, so a resend put an older comment back over a correction.
- `anam_dreamstation` labels no snapshot when the card holds an events file without its summary
  (anam card 99): the run cannot carry that session, so Anam must not be told it is absent.

### Added

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

### Fixed

- `anam_dreamstation` fetches the decoder as the tag's zip archive, not `git+https`: the gateway
  has no git, so uv could not resolve it.

- The README's gateway examples set `timeouts:` per command. A flat `timeout:` is not a ductile
  plugin field: `config check` passes it, and the gateway then crash-loops at boot.

### Changed

- `anam_bp_csv` emits `health.blood-pressure` v3, the body Anam bundles from its card 71
  (descriptions and examples added, no contract change). It needs an Anam with that release:
  an older one refuses v3 as a bundled type it does not hold, and the new one refuses v2 as not
  current, so the importer and Anam deploy together.

- `anam_submit` reads its token from the vault secret its instance config names in
  `token_secret`, a new required key, instead of a fixed `ANAM_IMPORTER_TOKEN`. Vault secret
  names are lowercase and global, so one fixed name could not serve two importers. For
  Withings: `token_secret: anam_importer_token_withings`.

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
