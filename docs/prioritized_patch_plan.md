# Prioritized Patch Plan — R5 PR1 → PR6

This is the rollup of the R5 patch sequence. Each PR has a discrete goal and
definition-of-done. **PR1 = this branch**.

## PR1 — Foundation (this PR, branch `claude/r5-source-registry-and-validation-gates`)

**Goal**: Land registries + runtime + audit + tests so future PRs can be
registry-driven and gate-enforced.

**Definition of done**:
- [x] Branch `claude/r5-source-registry-and-validation-gates` cut from `origin/main`.
- [x] 7 audit deliverables in `docs/` (`repo_audit.md`, `source_inventory.csv`,
      `missing_modules.md`, `broken_imports.md`, `placeholder_detection.md`,
      `execution_roadmap.md`, this file).
- [x] `registries/source_registry.yaml` (+ .json) declaring 80+ source rows.
- [x] `registries/schema_registry.yaml` (+ .json) with 17 canonical tables.
- [x] `registries/manual_export_registry.yaml` (+ .json) declaring manual-only sources.
- [x] `registries/endpoint_candidates.yaml` (+ .json) for endpoint health checks.
- [x] `contract_sweeper/runtime/` with 9 modules:
      `source_registry`, `schema_registry`, `manifest_runtime`, `validation_gates`,
      `name_normalization`, `linkage_confidence`, `file_hash_runtime`,
      `retry_runtime`, `pagination_runtime`.
- [x] `scripts/scan_for_secrets.py`.
- [x] `scripts/regenerate_registry_json.py`.
- [x] 7 new tests under `tests/` + fixtures under `tests/fixtures/r5/`.
- [x] `requirements.txt` adds `PyYAML`, `networkx`.
- [x] `.env.example` adds `HGOV_API_KEY`, `FELT_API_KEY`.
- [x] CI: `.github/workflows/ci.yml` adds validation-gates + secret-scan steps
      (in `--allow-failed` bootstrap mode).
- [x] `python -m compileall contract_sweeper scripts tests` → exit 0.
- [x] `pytest -q` → new tests pass; existing tests untouched.
- [x] `python -m contract_sweeper.runtime.validation_gates --allow-failed` writes
      `data/manifests/validation_report.json`.
- [x] `python scripts/scan_for_secrets.py` → exit 0.

## PR2 — Top-5 source materialization

**Goal**: Run USAspending prime, SAM entities, FEMA PA v2, LDA, FEC end-to-end
under the registry. Emit canonical manifests. Flip those 5 gates from
bootstrap to enforced.

**Definition of done**:
- Each producer_script writes a per-source manifest via `manifest_runtime`.
- `data/staging/processed/` has the 5 declared `expected_outputs`.
- `data/manifests/<source_id>/<timestamp>.json` exists for all 5.
- `validation_gates --root .` returns non-zero on missing top-5 outputs (gates
  enforced for these 5 only).
- Port `alias_registry_builder.py` + `parent_collapse.py` from sibling and run
  on the materialized data.
- Emit `entities_resolved.csv` + `high_value_unresolved.csv`.
- New tests cover per-source ingestion paths.

## PR3 — Execution chains

**Goal**: Build funding → prime → sub → asset → municipality chains.

**Definition of done**:
- Port `execution_chain_builder.py`.
- Emit `execution_chain_master.csv`, `execution_chain_per_asset.csv`,
  `execution_chain_per_municipality.csv`.
- `subaward_linkage_rate` and `execution_chain_linkage_rate` gates pass at
  ≥ 0.90 on real data.

## PR4 — Graphs (influence + asset/geo)

**Goal**: Build the influence_graph.gexf + asset_control_graph.gexf +
top_25_control_entities.csv + assets_master.geojson.

**Definition of done**:
- Port `influence_graph_builder.py`.
- Add `geo_runtime.py` + `assets_taxonomy.py` runtime helpers.
- Add `geopandas`/`shapely` to `requirements-geo.txt` (optional extras file
  so core install stays light).
- Emit `top_25_control_entities.csv` + `top_execution_entities.csv`.

## PR5 — Gap analysis + cleanup

**Goal**: Quantify what's missing per source; produce a backfill plan.

**Definition of done**:
- `scripts/gap_analysis.py` reads `source_manifest.json` + `source_registry.yaml`
  and computes year_coverage, completeness, freshness, etc. per source.
- Emit `data/reports/gap_analysis_report.csv` + `docs/backfill_plan.md`.
- Quarantine stale r4_X exports/manifests via
  `scripts/quarantine_stale_outputs.py`. Move to `data/_archive/r4_x/`.

## PR6 — Manual-export ingestion

**Goal**: Wire HUD DRGR authorized, FEMA 178-PW, PR corporate registry,
ACT/ACUDEN/DCAA legacy spreadsheets to their declared drop zones.

**Definition of done**:
- For each manual-export source: write `scripts/ingest_<source>.py` reading from
  `data/manual/<source_id>/`. Reject if columns missing.
- Emit per-source manifests.
- Document operator workflow in `docs/MANUAL_EXPORT_OPERATIONS.md`.
- Only build after user confirms the source files actually exist in
  `Contract-Sweeper-Secrets/` or a designated manual drop zone.

## PR7+ — Long-tail ingestion + governance flip

**Goal**: Ingest remaining 75 registered sources. Flip all gates from
`--allow-failed` to enforced.

## Out-of-scope (across all PRs)

- Credentialed portal scraping (DRGR, FEMA 178-PW portal). Manual export only.
- Refactor of the 50 R4 meta-orchestration modules in `contract_sweeper/pipeline/`.
  They stay until they're empirically unused; cleanup is deferred.
- Refactor of `run_all.py` into a registry-driven dispatcher. Hooks only in PR1.
