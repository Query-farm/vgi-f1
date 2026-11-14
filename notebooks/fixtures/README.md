# Recorded Jolpica-F1 responses

Source: [Jolpica-F1](https://github.com/jolpica/jolpica-f1), Ergast-compatible public API. Responses were fetched on November 14, 2026, with exact UTC bounds, URLs, status codes, byte lengths and SHA-256 hashes in `manifest.json`. The response bodies are unmodified. Both responses fit a single 100-row page: 56 lap timings for Max Verstappen and 40 pit stops across the 2024 Chinese Grand Prix field. This is independent recording for the notebook, not the repository's trimmed test fixtures.

Data and the notebook's derived data outputs are available under [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/), attributed to Jolpica-F1; see [upstream terms](https://github.com/jolpica/jolpica-f1/blob/main/TERMS.md). The worker and notebook helper code retain the repository's MIT license. No affiliation with Formula 1, the FIA or their associated companies is implied.

The replay helper verifies hashes and serves only these exact paths with offset 0/limit 100. Unsupported requests fail; no live or synthetic fallback occurs. The unchanged Git-pinned VGI worker performs its usual HTTP retrieval and parsing against that local endpoint.
