# Changelog

All notable changes to this project are documented here.

## 0.3.0 (2026-11-25)

- Speaks VGI protocol 3.4: require vgi-python `>=0.55.1,<0.56`; uv.lock re-locked. This release
  needs Haybarn 2.0.1 (or stock DuckDB 2.0 with `INSTALL vgi FROM query_farm`): Haybarn 2.0.0
  loads a 3.3 `vgi` extension that cannot attach it.
- SQL tests run on haybarn-unittest 2.0.1rc3 (CI and Makefile).
- `serve` extra includes `vgi-python[http,oauth]`; the Docker image installs it, so the image runs in
  Orchard hosted mode (`VGI_ORCHARD_HOSTED=1` with VGI_JWT_ISSUER, VGI_JWT_AUDIENCE,
  VGI_JWT_JWKS_URI and VGI_SIGNING_KEY). The Docker HEALTHCHECK uses `HEAD /health`, which
  stays anonymous in hosted mode.

## 0.2.3 (2026-11-16)

- Move to Python 3.14: `requires-python >=3.14`, CI, the Docker image and lint tooling target 3.14.
- CI runs the SQL tests through the starter's `ci/run-integration.sh` over stdio, launch and HTTP.

## [Unreleased]

## 0.2.2 (2026-11-16)

- Bump vgi-python to 0.52.2.

## [0.2.1]

- Docs link to Jolpica-F1, OpenF1 and their CC BY-NC-SA 4.0 licence: the
  catalog's documentation gains a Sources and references section (vgi-lint
  VGI183).

## [0.2.0]

- Port to VGI protocol 3.3 (vgi-python 0.51). Requires the current VGI DuckDB
  extension; 3.2 extensions are incompatible. No SQL surface changes: the
  `all_*` scan functions stay public.

## [0.1.0]

- Initial release on VGI protocol 3.2 (vgi-python 0.50), linted with
  vgi-lint-check 2.2.0.
- Current-season tables: `current_driver_standings`,
  `current_constructor_standings`, `current_schedule`, `last_race_results`, and
  `seasons`.
- Jolpica-F1 functions for 1950-present calendars, race, sprint, and
  qualifying results, championships by round, lap times, pit stops, driver
  histories, and driver, constructor, and circuit reference data.
- OpenF1 functions for 2023+ meetings, sessions, entry lists,
  classifications, laps and sectors, tyre stints, pit stops, weather, race
  control messages, and team radio links.
- Typed Arrow schemas with exact decimal points and lap times, column
  comments, discovery metadata, and agent test tasks.
- HTTP client with per-source sliding-window rate limits, bounded in-process
  caching, retries with `Retry-After`, complete pagination, and a total query
  deadline; production HTTP entry point that fails closed.
