# Execution Roadmap — Current vs Target State

This roadmap restates the mission pipeline order (steps 1 → 15 in the takeover
brief) and shows each layer's current vs target state.

| Step | Layer | Current state | Target state |
|---|---|---|---|
| 1 | Repo inventory | Done (R5 PR1: `repo_audit.md`, `source_inventory.csv`, etc.) | Audit refreshed each PR. |
| 2 | Source registry | Done (R5 PR1: `registries/source_registry.yaml` + .json, 80+ sources). | Continuously extended as new sources are confirmed. |
| 3 | Schema registry | Done (R5 PR1: `registries/schema_registry.yaml` + .json, 17 canonical tables). | Extended when new tables emerge (geo, control graphs). |
| 4 | Runtime utilities | Done (R5 PR1: `moneysweep/runtime/` — 8 modules). | Add `geo_runtime`, `assets_taxonomy` in later PR. |
| 5 | Ingestion modules | ~100 scripts exist; none registry-bound. | PR2 flips top-5 sources to registry-driven manifests. |
| 6 | Normalization | Partial in scripts/ ingest modules. | PR2/PR3 normalizes via `schema_registry` mappings. |
| 7 | Alias registry | Missing. | PR2/PR3 ports `alias_registry_builder.py`. |
| 8 | Entity resolution | Missing. | PR2/PR3 ports `parent_collapse.py`. |
| 9 | Execution chains | Missing. | PR3 ports `execution_chain_builder.py`. |
| 10 | Geo / asset graph | Missing. | PR4 builds `assets_master.geojson` + `asset_control_graph.gexf`. |
| 11 | Influence graph | Missing. | PR4 ports `influence_graph_builder.py`. |
| 12 | Gap analysis loop | Missing. | PR5 builds `gap_analysis.py` + `backfill_plan.md`. |
| 13 | Validation gates | Done (R5 PR1: `moneysweep/runtime/validation_gates.py`, 7+ gates). | Flipped from `--allow-failed` to enforced after PR2 lands real data. |
| 14 | Export | Partial; r4 artifacts under `data/exports/`. | PR2+ writes canonical mission outputs under `data/processed/`, `data/graphs/`, `reports/`, `data/manifests/`. |
| 15 | Tests | 58 backfill/recovery tests exist; canonical tests missing. | R5 PR1 adds 7 canonical tests; PR2+ adds source-specific. |

## R5 PR1 deliverables (this PR)

- 7 audit deliverables in `docs/`.
- 4 registry files (`source_registry`, `schema_registry`, `manual_export_registry`,
  `endpoint_candidates`) in both YAML (source of truth) and JSON (wire).
- 9 runtime modules in `moneysweep/runtime/`.
- 7 new tests covering registries, runtime, gates, secret scan.
- Updated `requirements.txt`, `.env.example`.
- CI extended with validation-gates + secret-scan steps (in `--allow-failed`
  bootstrap mode).
- No production data was modified; r4 artifacts left intact.

## R5 PR2 (next)

- Materialize top 5 sources end-to-end: USAspending prime, SAM entities,
  FEMA PA OpenFEMA v2, LDA, FEC.
- Each writes a per-source manifest via `manifest_runtime`.
- Flip their validation gates to enforced.
- Port `alias_registry_builder.py` + `parent_collapse.py` and run on the
  materialized data; emit `entities_resolved.csv` + `high_value_unresolved.csv`.

## R5 PR3

- Execution chains over materialized data.
- Emit `execution_chain_master.csv` + `execution_chain_per_asset.csv` +
  `execution_chain_per_municipality.csv`.

## R5 PR4

- Influence graph + top_25_control_entities.
- Geo/asset graph (assets_master.geojson + asset_control_graph.gexf).

## R5 PR5

- Gap analysis loop + `gap_analysis_report.csv` + `backfill_plan.md`.
- Cleanup of stale r4_X artifacts.

## R5 PR6

- HUD DRGR authorized export ingestion + FEMA 178-PW portal export
  ingestion (manual drops only).
- ACT / ACUDEN / DCAA legacy spreadsheet parsers (manual drops only).
- Only built once we confirm the source files are physically present in
  `moneysweep-pr-Secrets/` or a designated manual drop zone.
