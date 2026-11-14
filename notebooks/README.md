# Formula 1 notebooks

[01 · How much does a pit-adjacent lap filter change a stint summary?](01_pit_lap_filters_change_stint_summaries.ipynb) inspects Max Verstappen's 2024 Chinese Grand Prix laps, groups them at recorded stops, and compares retained lap-time distributions. The experiment disables only the pit-adjacent exclusion.

## Run

Requirements: [uv](https://docs.astral.sh/uv/), Git, Python 3.13+ (uv can install it), and internet access for package/Git downloads. Default replay needs no API credentials or surrounding worker checkout. Live mode additionally needs Jolpica-F1 access.

```sh
cd notebooks
uv sync --locked
uv run --locked python execute.py --timeout 300
```

The locked notebook environment uses Haybarn 2.0.0rc11. Visible SQL uses the literal command `uvx --from git+https://github.com/Query-farm/vgi-f1@v0.2.0 --with vgi-python==0.51.0 --with vgi-rpc==0.53.1 --with httpx==0.28.1 --with pyarrow==25.0.1 vgi-f1`. The published Git tag resolves to `dae778b4965cc878ff00315834976d6c66d2bdff`; the worker is not on PyPI. uv installs this source in its cache. Upgrade the release and compatible dependency pins deliberately, then rerun replay, experiment and live checks.

Optional editor kernel:

```sh
uv run --locked python -m ipykernel install --user --name vgi-f1-notebooks --display-name "Python (vgi-f1 notebooks)"
```

Use this directory as working directory, then Restart Kernel → Run All. The runner registers a temporary kernel automatically and replaces saved output only on complete success.

## Separate experiment and live check

```sh
uv run --locked python execute.py --parameters '{"EXCLUDE_PIT_ADJACENT":false}' --output-dir artifacts/all-laps
uv run --locked python execute.py --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live
```

The experiment keeps replay and changes only the filter. Restore `True` afterward. Live is a separate source check for the same finished race, not a switch to the current season. Overrides require a separate destination; branding, recorded responses, replay helper, docs and locked environment accompany the executed copy. Logs, charts, experiments and virtual environments are ignored.

## Provenance and data license

Source: [Jolpica-F1](https://github.com/jolpica/jolpica-f1), Ergast-compatible API. Two complete responses were recorded on November 14, 2026: 56 driver lap timings and 40 field pit stops for season 2024/round 5. Exact capture UTC bounds, URLs, reported totals, bytes and hashes are in [fixtures/manifest.json](fixtures/manifest.json); original response bodies are unchanged. These are independent complete recordings, not the repository's trimmed test fixtures. See [fixture attribution](fixtures/README.md).

Data and derived notebook data outputs retain [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) attribution to Jolpica-F1 under its [published terms](https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md). The worker and helper code retain MIT licensing. This project is not affiliated with Formula 1, the Formula One group or the FIA.

The replay helper hash-checks and serves only the exact recorded paths at offset 0/limit 100. It binds a local ephemeral port; unsupported requests fail. The unchanged VGI worker still performs HTTP retrieval and parsing. Live explicitly selects official endpoints and never falls back to replay or synthetic values. Capture times, this run's retrieval bounds and a materialized-data fingerprint are displayed separately. Historical corrections can change a live run.

## Interpretation

The lap request supplies the driver as an API argument; pit stops are bounded to one race and filtered locally. Each is materialized once. Stint number is one plus the number of stops on earlier laps: the stop lap belongs to the preceding group. These groups do not identify tyre compound/age. Pit-adjacent exclusion removes the stop lap and its following lap from summaries while retaining them in the raw chart.

Lap and pit-lane durations are seconds. Pit-lane time includes entry to exit, not merely stationary service; its separate wall-clock string is not assumed UTC. Quartiles describe the retained distribution, not uncertainty in an estimated pace. Starting-lap, traffic, safety-car, flag, weather and fuel effects remain. These observations do not establish equal-condition racing pace or causal tyre/driver differences.
