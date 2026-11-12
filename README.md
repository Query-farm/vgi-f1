<p align="center">
  <a href="https://query.farm/vgi/">
    <img src="https://raw.githubusercontent.com/Query-farm/vgi-kalshi/main/docs/vgi-logo.png" alt="Vector Gateway Interface logo" width="320">
  </a>
</p>

<h1 align="center">vgi-f1</h1>

<p align="center">
  Formula 1 championships, results, calendars, lap times, and session timing as ordinary DuckDB tables.<br>
  A <strong>read-only</strong> <a href="https://query.farm/vgi/">VGI</a> worker, built by <a href="https://query.farm">🚜 Query.Farm</a>
</p>

<p align="center">
  <a href="https://github.com/Query-farm/vgi-f1/actions/workflows/ci.yml"><img src="https://github.com/Query-farm/vgi-f1/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="MIT license"></a>
  <img src="https://img.shields.io/badge/python-3.13%2B-3776AB.svg" alt="Python 3.13+">
  <a href="https://query.farm/vgi/"><img src="https://img.shields.io/badge/VGI-read--only-6f42c1.svg" alt="Read-only VGI worker"></a>
</p>

---

`vgi-f1` fetches data on demand from two community-run, keyless APIs and
reformats the responses as typed Arrow data for Haybarn SQL:

- [Jolpica-F1](https://github.com/jolpica/jolpica-f1), the Ergast-compatible
  archive: calendars, results, qualifying, sprints, championships by round,
  lap times (1996+), pit stops (2011+), drivers, constructors, and circuits
  from 1950 to the present.
- [OpenF1](https://openf1.org): 2023+ session-level timing from the keyless
  historical tier: meetings, sessions, entry lists, classifications, laps and
  sectors, tyre stints, pit stops, weather, race control, and team radio links.

It requires no credentials and does not rehost or persist either dataset.

## Quick start

The worker is not published to PyPI. `uvx` runs the tagged release straight from
GitHub and caches it after the first use:

```bash
uvx --from git+https://github.com/Query-farm/vgi-f1@v0.2.0 vgi-f1 --help
```

Launch Haybarn with the catalog pre-attached:

```bash
uvx haybarn-cli \
  -cmd "INSTALL vgi FROM community; LOAD vgi; ATTACH 'f1' (TYPE vgi, LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-f1@v0.2.0 vgi-f1');" \
  :memory:
```

Or attach it in an existing Haybarn session:

```sql
INSTALL vgi FROM community;
LOAD vgi;
ATTACH 'f1' (
  TYPE vgi,
  LOCATION 'uvx --from git+https://github.com/Query-farm/vgi-f1@v0.2.0 vgi-f1'
);
```

For source development, run `uv lock --check --no-sources`, then
`uv sync --no-sources` and `uv run --no-sources vgi-f1`.
The lockfile resolves all dependencies from package registries and does not
require a sibling checkout.

## Catalog surface

The catalog exposes five ordinary tables and twenty-two parameterized table
functions:

| Kind | Objects |
| --- | --- |
| Current season | `current_driver_standings`, `current_constructor_standings`, `current_schedule`, `last_race_results`, `seasons` |
| Championships | `driver_standings(season, round := NULL)`, `constructor_standings(season, round := NULL)` |
| Results | `race_results(season, round := NULL)`, `sprint_results(season, round := NULL)`, `qualifying_results(season, round := NULL)`, `driver_results(driver_id, season := NULL)` |
| Calendar | `schedule(season)` |
| Race timing | `lap_times(season, round, driver_id := NULL)`, `pit_stops(season, round)` |
| Reference | `drivers(season := NULL)`, `constructors(season := NULL)`, `circuits(season := NULL)` |
| OpenF1 sessions (2023+) | `meetings(season)`, `sessions(season, session_name := NULL)`, `session_drivers(session_key)`, `session_result(session_key)`, `session_weather(session_key)`, `race_control(session_key)`, `team_radio(session_key, driver_number := NULL)` |
| OpenF1 timing (2023+) | `session_laps(session_key, driver_number := NULL)`, `session_stints(session_key)`, `session_pits(session_key)` |

Each `current_*` table and `seasons` is backed by an `all_*` scan function of
the same shape; query the table.

Jolpica-F1 objects are keyed by `season`, `round`, and stable text ids such as
`driver_id = 'max_verstappen'`, `constructor_id = 'mclaren'`, and
`circuit_id = 'monza'`. OpenF1 objects are keyed by `session_key` and car
`driver_number`; `session_drivers()` maps numbers to names and teams.

## Usage

### Championships

```sql
-- Who leads the title race right now, and by how much?
SELECT position, driver_name, constructor_name, points, wins,
       max(points) OVER () - points AS gap_to_leader
FROM f1.main.current_driver_standings
ORDER BY position;

SELECT position, constructor_name, points, wins
FROM f1.main.current_constructor_standings
ORDER BY position;

-- Final 2024 drivers' championship, and the table after round 10
SELECT position, driver_name, points, wins
FROM f1.main.driver_standings(2024)
ORDER BY position;

SELECT position, driver_name, points
FROM f1.main.driver_standings(2024, round := 10)
ORDER BY position;
```

Points are exact `DECIMAL(7,2)` values (half points exist). `constructor_id`
is `NULL` when a driver raced for more than one team in the season, rather than
crediting only one of them; `constructor_ids` and `constructor_names` list every
team.

### Calendar and results

```sql
-- Remaining rounds this season, with UTC session times
SELECT round, race_name, country, qualifying_utc, race_start_utc, is_sprint_weekend
FROM f1.main.current_schedule
WHERE race_date >= current_date
ORDER BY round;

-- Podium of the most recent Grand Prix
SELECT position, driver_name, constructor_name, race_time
FROM f1.main.last_race_results
WHERE position <= 3
ORDER BY position;

-- Grand Prix and sprint wins per driver in 2024
SELECT driver_name, count(*) AS wins
FROM f1.main.race_results(2024)
WHERE position = 1
GROUP BY driver_name
ORDER BY wins DESC;

SELECT round, race_name, driver_name
FROM f1.main.sprint_results(2024)
WHERE position = 1;

-- Pole positions with exact Q3 seconds
SELECT round, race_name, driver_name, q3, q3_seconds
FROM f1.main.qualifying_results(2024)
WHERE position = 1
ORDER BY round;

-- Lewis Hamilton's career wins and podiums
SELECT count(*) FILTER (WHERE position = 1) AS wins,
       count(*) FILTER (WHERE position <= 3) AS podiums
FROM f1.main.driver_results('hamilton');
```

`position` is the classification order including retirements; `classified` is
true only when the published `position_text` is numeric (`R`, `D`, `E`, `W`, `F`,
and `N` mark retirements, disqualifications, exclusions, withdrawals, failures
to qualify, and non-classification). A `grid` of `0` is a pit-lane start.

### Lap times and pit stops

```sql
-- Max Verstappen's laps in the 2024 Chinese Grand Prix (round 5)
SELECT lap, position, lap_time, lap_time_seconds
FROM f1.main.lap_times(2024, 5, driver_id := 'max_verstappen')
ORDER BY lap;

SELECT driver_id, stop, lap, duration_seconds
FROM f1.main.pit_stops(2024, 5)
ORDER BY duration_seconds
LIMIT 5;
```

Pass `driver_id` to `lap_times()` whenever you can: a full race is about 1,100
rows fetched over 10-15 upstream pages, while one driver is a single request.
Pit-stop durations are pit-lane entry-to-exit times, not stationary times.

### Session timing from OpenF1

Find a `session_key` with `sessions()`, then use it with the `session_*`
functions:

```sql
SELECT session_key, country_name, location, date_start
FROM f1.main.sessions(2024, session_name := 'Race')
ORDER BY date_start;

-- 2024 Bahrain Grand Prix (session 9472): classification with names
SELECT r.position, d.full_name, d.team_name, r.points, r.gap_to_leader
FROM f1.main.session_result(9472) r
JOIN f1.main.session_drivers(9472) d USING (driver_number)
ORDER BY r.position;

-- Tyre strategy
SELECT d.name_acronym, s.stint_number, s.compound, s.lap_start, s.lap_end
FROM f1.main.session_stints(9472) s
JOIN f1.main.session_drivers(9472) d USING (driver_number)
ORDER BY d.name_acronym, s.stint_number;

-- Fastest laps with sector splits
SELECT driver_number, lap_number, lap_duration,
       duration_sector_1, duration_sector_2, duration_sector_3, st_speed
FROM f1.main.session_laps(9472)
WHERE lap_duration IS NOT NULL
ORDER BY lap_duration
LIMIT 10;

-- Conditions and incidents
SELECT min(track_temperature), max(track_temperature), bool_or(rainfall)
FROM f1.main.session_weather(9472);

SELECT date, lap_number, flag, message
FROM f1.main.race_control(9472)
WHERE category = 'Flag'
ORDER BY date;
```

For qualifying sessions `session_result()` fills `q1_seconds`, `q2_seconds`, and
`q3_seconds`. Lapped gaps such as `+1 LAP` stay in `gap_to_leader` with a `NULL`
numeric `gap_to_leader_seconds`. `team_radio()` returns links to the official
audio clips; the audio itself is never fetched or rehosted.

OpenF1's very large feeds (car telemetry, location, and intervals) are
deliberately not exposed: they run to many megabytes per session and OpenF1
rejects unfiltered location requests. Live, in-session data is on OpenF1's paid
tier and is not used; sessions appear here once OpenF1 publishes them to the
free historical tier, shortly after they finish.

## Data sources, licence, and affiliation

**This project is not affiliated with, endorsed by, or associated with Formula 1,
the Formula One group of companies, or the FIA.** F1, FORMULA ONE, FORMULA 1,
and GRAND PRIX are trade marks of Formula One Licensing B.V.

Both upstream datasets are published under the
[Creative Commons Attribution-NonCommercial-ShareAlike 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/)
licence (CC BY-NC-SA 4.0):

- Results and championship data: [Jolpica-F1](https://github.com/jolpica/jolpica-f1),
  successor to the Ergast Developer API.
- Session timing data: [OpenF1](https://openf1.org).

What that means for you:

- **Attribution.** Credit Jolpica-F1 and/or OpenF1 when you publish results
  derived from this catalog.
- **Non-commercial.** The data may not be used for commercial purposes. The
  MIT licence below covers this worker's code only; it does not relicense the
  data.
- **ShareAlike.** Datasets you derive and distribute must use the same licence.

`vgi-f1` fetches on demand and caches responses only in process memory for a
bounded time. It does not store, mirror, or redistribute either dataset. It
respects both services' published rate limits (Jolpica-F1: 4 requests per
second and 500 per hour; OpenF1: 30 requests per minute) and identifies itself
with an honest `User-Agent`. Both services are run by volunteers; please keep
queries reasonable.

## Production HTTP deployment

Stdio is the recommended transport when Haybarn can launch the worker locally.
Use HTTP when the worker must be shared across hosts. The production HTTP entry
point fails closed unless it has a stable signing key and either authentication
or an explicit anonymous-access decision:

```bash
export VGI_SIGNING_KEY='a-long-random-secret-shared-by-every-replica'
export VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn'

uvx --from git+https://github.com/Query-farm/vgi-f1@v0.2.0 vgi-f1-http \
  --host 0.0.0.0 \
  --port 8000 \
  --cors-origins 'https://sql.example.com' \
  --log-format json
```

`vgi-f1-http` disables the description pages and cross-origin access unless
they are explicitly configured. Terminate TLS at a trusted proxy or load
balancer. All replicas must receive the same `VGI_SIGNING_KEY`; rotate it as a
coordinated deployment because outstanding state tokens are signed with it.

Supported authentication options are:

- `VGI_BEARER_TOKENS`: comma-separated `token=principal` pairs.
- `VGI_JWT_ISSUER` and `VGI_JWT_AUDIENCE`: JWT/JWKS authentication.
- `VGI_PROXY_PROOF_MODE=require` with the corresponding VGI proxy-proof
  settings when a trusted proxy authenticates users.

Because this connector exposes read-only public data, an intentionally public
service can set `VGI_ALLOW_ANONYMOUS=1`. It should still be protected by gateway
rate limits: every replica spends the same small upstream budgets. The health
probe is `GET /health`.

### Container

```bash
docker build -t vgi-f1 .
docker run --rm -p 8000:8000 \
  -e VGI_SIGNING_KEY='replace-with-a-stable-random-secret' \
  -e VGI_BEARER_TOKENS='replace-with-a-random-token=haybarn' \
  vgi-f1
```

The image runs as an unprivileged user, emits JSON logs, disables interactive
description pages, and includes a health check.

## Reliability and operations

- **Caching.** Responses are cached in process (bounded LRU, 256 entries).
  Current-season Jolpica-F1 data is reused for the origin's `max-age` (ten
  minutes today); finished seasons are reused for six hours; OpenF1 session
  data for one hour. The same lifetime is forwarded to VGI clients as
  `Cache-Control`, so Haybarn can also reuse results.
- **Rate limits.** A sliding-window limiter per source enforces Jolpica-F1's
  4/second and 500/hour and OpenF1's 3/second and 30/minute. If a query would
  have to wait past its deadline, it fails with a clear rate-limit error rather
  than hammering the service.
- **Retries.** HTTP 429 and transient 5xx responses and transport errors are
  retried up to four attempts with exponential backoff and jitter; `Retry-After`
  is honored with a 30-second cap. Redirects are followed.
- **Timeouts.** Each request has a 30-second timeout (10 seconds to connect) and
  each logical fetch a 120-second deadline across all pages and retries.
- **Pagination.** Jolpica-F1 pages at 100 rows. Table functions stream one
  Arrow batch per upstream page (up to 30), carrying the offset in serializable
  scan state, so the first rows arrive after one request and results are never
  silently truncated. A race whose rows continue onto the next page simply
  continues in the next batch.
- **Empty results.** OpenF1 answers 404 when a filter matches nothing; that is
  returned as zero rows. OpenF1's 422 "too much data" is reported as an error.

`F1_JOLPICA_BASE_URL` and `F1_OPENF1_BASE_URL` may point to alternate roots for
hermetic tests. Do not set them from untrusted user input.

## Development and release checks

```bash
uv lock --check --no-sources
uv sync --no-sources
uv run --no-sources ruff check .
uv run --no-sources ruff format --check .
uv run --no-sources pytest --cov=vgi_f1 --cov-fail-under=80
uv build
uvx twine check dist/*
uvx --no-sources --from vgi-lint-check==2.2.0 vgi-lint lint \
  'uv run --no-sources f1_worker.py' \
  --no-execute --no-check-links --audit-waivers --fail-on warning
```

The offline suite parses trimmed real API responses in `tests/fixtures/` and
includes a hermetic Haybarn end-to-end test that serves those fixtures from a
local HTTP server. Live upstream smoke tests are opt-in with
`uv run pytest -m live` and run, with the executing `vgi-lint` pass over every
catalog example, in a serialized scheduled workflow.

Publishing is driven by releases. Create a GitHub release named `vX.Y.Z` that
matches the version in `pyproject.toml`. CI then builds, validates and attests
the wheel and sdist, attaches them to the release, and publishes a
multi-platform container image to `ghcr.io/query-farm/vgi-f1`. The package is
not published to PyPI; install it from the release tag as shown in the quick
start.

## License

Copyright 2026 Query Farm LLC - https://query.farm

The worker's source code is released under the [MIT License](LICENSE). Data
returned by the worker remains subject to the upstream CC BY-NC-SA 4.0 licence
described above.
