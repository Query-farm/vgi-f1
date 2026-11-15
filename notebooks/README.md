# Formula 1 Data notebooks

Three executed SQL stories use the released [Formula 1 Data worker](https://github.com/Query-farm/vgi-f1). Each notebook has an **Open in Colab** link, visible VGI connection SQL, an editable experiment and SVG charts.

| Notebook | Question | Experiment |
| --- | --- | --- |
| [Pit-adjacent lap filters](01_pit_lap_filters_change_stint_summaries.ipynb) | Which laps define a stint summary? Preserve the original 2024 Chinese GP analysis. | Include the four previously excluded laps. |
| [Separate weekend classifications](02_a_weekend_has_separate_classifications.ipynb) | How do qualifying, starting grid, race results and sprint points differ? | Remove sprint points from the local weekend total. |
| [Weather and lap clocks](03_weather_context_needs_a_time_tolerance.ipynb) | How fresh must a preceding weather reading be? Resolve the 2024 Bahrain race, driver, stints and pit context first. | Reduce the allowed weather age from 60 to 15 seconds. |

## Run

Colab opens the notebook directly; run its short bootstrap and then all cells. It installs the shared **base** package and retrieves checksum-verified companion files. Compatible preloaded plotting, pandas and kernel libraries are retained. Restart the kernel before changing source mode. GitHub shows setup cells expanded; folding metadata only assists editors.

For local publication, install [uv](https://docs.astral.sh/uv/) and Git, then:

```sh
cd notebooks
uv run --locked vgi-notebooks --timeout 300
```

The local lock uses the shared package's `[runner]` extra; Colab never installs that extra. The visible worker command is:

```sql
ATTACH 'f1' (
    TYPE vgi,
    LOCATION 'uvx --python 3.13 --from git+https://github.com/Query-farm/vgi-f1@v0.2.0 vgi-f1'
);
```

The published v0.2.0 tag resolves to `dae778b4965cc878ff00315834976d6c66d2bdff`. Its isolated environment owns the worker's dependency ranges; the notebook does not override transitive dependencies. First execution needs internet access to obtain public packages, release source and companions. There is no worker compilation or manual source checkout step.

Experiments must use a separate destination, preserving the saved defaults:

```sh
uv run --locked vgi-notebooks 01_pit_lap_filters_change_stint_summaries.ipynb --parameters '{"EXCLUDE_PIT_ADJACENT":false}' --output-dir artifacts/all-laps
uv run --locked vgi-notebooks 02_a_weekend_has_separate_classifications.ipynb --parameters '{"INCLUDE_SPRINT":false}' --output-dir artifacts/without-sprint
uv run --locked vgi-notebooks 03_weather_context_needs_a_time_tolerance.ipynb --parameters '{"MAX_WEATHER_AGE_SECONDS":15}' --output-dir artifacts/fresher-weather
uv run --locked vgi-notebooks --parameters '{"DATA_MODE":"live"}' --output-dir artifacts/live
```

Live mode queries the same finished events through official public endpoints. It never falls back to recordings. Historical corrections and service availability can change a live run. The default is reproducible replay through the real released worker.

## Source provenance and interpretation

The first story retains its two original, complete Jolpica-F1 responses from November 14, 2026: 56 Max Verstappen laps and 40 field pit stops for the 2024 Chinese GP. Original bytes and [manifest](fixtures/manifest.json) are unchanged. Stop laps belong to the preceding group; excluding a stop lap and its following lap affects only summaries. Quartiles describe retained observations, not uncertainty or equal-condition pace. These groups alone do not identify tyre compound or age.

The second story uses seven complete official Jolpica-F1 responses acquired November 15, 2026 UTC, with 20 race entries, a 25-driver season reference, ten constructors and event/circuit context. Grand Prix points sum to 102 and sprint points to 36. The two events remain separate source columns when the experiment changes the selected total from 138 to 102. Grid-to-finish position changes are not an observed overtaking count.

The third story uses eight complete official OpenF1 responses acquired November 15, 2026 UTC. Meeting and session keys distinguish the Bahrain Grand Prix from pre-season testing. Hamilton's 57 laps join three published stint intervals; the two pit records supply lane durations but no stationary stop duration. A backwards ASOF join preserves every lap and never borrows future weather. Missing or stale temperatures are not zero, and an age limit does not identify causes of lap-time changes.

The compressed JSON packs under `recordings/` contain complete original response bytes as base64, request URLs, exact query parameters, status codes, capture bounds and SHA-256 hashes. The helper checks these bytes, serves only exact loopback requests and audits each requested population (2, 7 or 8 calls). Source capture time and this notebook's retrieval time are separate; multi-request data is not an atomic snapshot. No synthetic race records are used.

[Jolpica-F1](https://github.com/jolpica/jolpica-f1) data and derived outputs retain [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) attribution under its [terms](https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md). [OpenF1](https://openf1.org/) historical responses retain provider attribution; source data rights remain with their providers. Worker/helper code retains its repository license. No affiliation with Formula 1, the Formula One group or the FIA is implied.

## Coverage and shared tools

[coverage.json](coverage.json) maps successful visible SQL to **17 of 32 logical public surfaces**, above the 16-object threshold. Both the release and current source catalogs are complete; differently named backing scans and relations remain separate objects. Current source differs in examples and metadata only. Current-interface compatibility is reviewed, while exact execution belongs to the released worker; no current-main runtime execution is claimed.

The [central notebook standard](https://github.com/Query-farm/vgi-example-notebooks/blob/main/docs/standard.md), runner, branding, setup and chart presentation live in [vgi-example-notebooks](https://github.com/Query-farm/vgi-example-notebooks). Domain replay/data companions stay here. Saved charts contain native SVG and content-addressed GitHub image references. Tests cover defaults, separate experiments, public live reads and one fresh notebook-only run with existing libraries preloaded; local compatibility testing is not a hosted Colab UI execution.
