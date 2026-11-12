# Changelog

All notable changes to this project are documented here.

## [Unreleased]

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
