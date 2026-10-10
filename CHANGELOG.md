# Changelog

All notable changes to this repo. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the repo follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html): one version for the base,
`anam_submit` and every importer, kept in `VERSION` and in each plugin manifest.

## [Unreleased]

### Added

- `anam_dreamstation`, the CPAP importer: a Philips DreamStation SD card copy as
  `sleep.cpap-session` v1, one facet per therapy session, holding only what the device wrote
  (times, mask-on spans, settings, its pressure summary and counts, a tally of the events
  file). Its Definition is registered through the API. Needs the `dreamstation` decoder.
- `anam_bp_csv`, the blood pressure importer: a phone app export (`BloodPressure_<date>`) as
  `health.blood-pressure` v2, the built-in `bpcsv` worker's reading moved, so the same export
  through either is the same facets. Runs on a `folder_watch` per-file event; `poll` resends
  every export under `export_dir`.

### Fixed

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
