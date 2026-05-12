# Repo Audit — R5 Foundation Snapshot

**Generated**: 2026-05-11
**Scope**: `/Users/jotaele/Documents/GitHub/Contract-Sweeper` plus sibling source folders.
**Auditor**: R5 takeover.

This document is the narrative companion to `source_inventory.csv`,
`missing_modules.md`, `broken_imports.md`, `placeholder_detection.md`,
`execution_roadmap.md`, and `prioritized_patch_plan.md`. It states only what
was observed; recommendations live in `prioritized_patch_plan.md`.

---

## 1. Mission gap at takeover

The repo target is an "intelligence-grade public-record reconstruction" of the
Puerto Rico contract / funding / infrastructure / lobbying / political-finance
ecosystem. The canonical outputs the mission requires are:

| Output | Present? |
|---|---|
| `contracts_master.parquet` | missing |
| `entities_resolved.csv` | missing |
| `alias_registry.json` | missing |
| `execution_chain_master.csv` | missing |
| `execution_chain_per_asset.csv` | missing |
| `top_execution_entities.csv` | missing |
| `influence_graph.gexf` | missing |
| `top_25_control_entities.csv` | missing |
| `gap_analysis_report.csv` | missing |
| `review_queue.csv` | missing (per-file slices exist) |
| `source_manifest.json` | missing (per-r4 manifests exist) |
| `validation_report.json` | missing |

**Zero of twelve canonical outputs exist.**

## 2. Core code layer (`contract_sweeper/`)

50 modules across `pipeline/`, `risk/` (empty), `validation/`. The package is
entirely backfill / freeze / unfreeze / recovery / blocker meta-orchestration
from the R4.5 → R4.9Z-F iterations. Notable modules:

- `pipeline/`: `acquisition_package`, `backfill_runner`, `controlled_backfill`,
  `external_blocker_freeze`, `source_delivery_handoff`, `source_recovery_pause_lock`,
  `schema_alignment`, `schema_remediation`, `source_manifest_writer`,
  `delivered_source_validation`, `unfreeze_guard`, etc.
- `validation/`: `source_coverage`, `source_input_recovery`, `entity_universe_audit`,
  `master_input_recovery`, `production_status`, `cache_audit`,
  `backfill_execution_plan`, `artifact_lineage`.
- `risk/`: package with `__init__.py` only.

**None of the modules ingest data from a source.** The actual ingestion lives
in `scripts/`. The package is meta about the meta.

## 3. `run_all.py` (113KB orchestrator)

Argparse-driven; defines 30+ skip flags spanning steps 1 → 30 with sub-letters
(a–v). The pipeline order encoded in the help strings covers: setup → auto-download
→ validation → normalization → dedup → SAM enrichment → entity resolution →
dominance → network graph → grants/FEMA/NIH/SBA/SLFRF/CDBG-DR → unified master
→ FEC/LDA/cross-ref → CMS/FDIC/SEC → influence network → MSRB EMMA → OFAC →
OpenCorporates → prime-to-sub → FSRS/COR3/comprashpr/OpenFEMA PA v2/FEMA 178-PW
→ HUD DRGR (public + authorized) → DRGR normalize/link → financial flows
master → Medicaid/SSA/Medicare/VA/USDA/AAFAF/pensions/EPA/USACE/NIH/FCC USF
→ DOL WHD/SEC 13F/GAO IG/P3/Medicare Advantage/CHIP/WIC/WIOA/HUD Section 8
→ NCUA/Hacienda/COFINA.

**No registry binds these step flags to canonical outputs or thresholds.** The
new `registries/source_registry.yaml` does.

## 4. `scripts/` directory (~157 files)

Real ingestion modules. Grouped:

- **Federal contracts**: `build_unified_master.py`, `download_grants.py`,
  `download_subawards.py`, `download_earmarks.py`, `download_fsrs.py`,
  `download_active_contractors.py`, `download_usace_civil.py`,
  `download_usace_permits.py`, `fetch_highergov_api.py`, `parse_highergov_pdfs.py`.
- **FEMA / disaster**: `download_fema.py`, `download_cor3.py`,
  `download_openfema_pa_projects.py`, `ingest_cor3.py`,
  `ingest_fema_pa_portal_exports.py`, `link_fema_pa_to_contracts.py`,
  `validate_fema_pa_coverage.py`.
- **HUD CDBG-DR**: `download_cdbg_dr.py`, `download_hud.py`,
  `download_hud_drgr_public.py`, `download_hud_hcv.py`,
  `ingest_hud_drgr_exports.py`, `normalize_hud_drgr.py`,
  `link_hud_drgr_to_assets.py`, `link_hud_drgr_to_contracts.py`,
  `validate_hud_drgr_amounts.py`, `validate_hud_drgr_coverage.py`.
- **SAM / entity resolution**: `sam_enrichment.py`, `entity_resolution.py`.
- **Lobbying**: `download_lda.py`, `lda_enrich.py`, `download_cabilderos.py`,
  `ingest_cabilderos.py`.
- **Political finance**: `download_fec.py`, `ingest_fec.py`,
  `ingest_follow_the_money.py`.
- **Banks / regulators**: `download_fdic.py`, `download_fhlb.py`,
  `download_ncua.py`, `download_sec.py`, `download_sec_holdings.py`.
- **Bonds**: `download_msrb_trades.py`, `download_emma.py`, `emma_mapper.py`,
  `analyze_bond_flow.py`.
- **Healthcare**: `download_cms.py`, `download_hhs.py`, `download_medicaid_fmap.py`,
  `download_medicare_advantage.py`, `download_medicare_parts.py`,
  `download_chip.py`, `cms_mapper.py`.
- **Other federal**: `download_dol.py`, `download_dot.py`, `download_doe.py`,
  `download_doj_grants.py`, `download_ed.py`, `download_epa.py`,
  `download_exim.py`, `download_gao_ig.py`, `download_oia.py`,
  `download_nih.py`, `download_nfip.py`, `download_sba.py`, `download_sbir.py`,
  `download_sf133.py`, `download_slfrf.py`, `download_va.py`, `download_wic.py`,
  `download_wioa.py`, `download_usda.py`, `download_ofac.py`, `download_ssa.py`,
  `download_snap_nap.py`, `download_nmtc.py`, `download_lihtc.py`,
  `download_haf.py`.
- **PR-specific territorial**: `download_aafaf.py`, `download_act60.py`,
  `download_cofina.py`, `download_compras.py`, `download_contralor.py`,
  `ingest_contralor.py`, `download_eqb.py`, `download_hacienda.py`,
  `download_municipal.py`, `download_p3.py`, `download_pr_pensions.py`,
  `download_prasa.py`, `ingest_prasa.py`, `download_prepa_contracts.py`,
  `download_promesa_creditors.py`, `download_rum_coverover.py`,
  `ingest_active_contractors.py`.
- **Entity res / network / analysis**: `entity_resolution.py`, `sam_enrichment.py`,
  `dominance_analysis.py`, `network_graph.py`, `link_*.py`, `analyze_*.py`.
- **r4_X recovery runners** (~25 files): wrappers around the meta-pipeline.

**Missing**: dedicated `alias_registry_builder`, `execution_chain_builder`,
`influence_graph_builder`, `parent_collapse`, `manifest_runtime`,
`source_registry`, `schema_registry`, `validation_gates` modules. R5 PR1
ports these from the sibling Contract-Sweep repo and lands them in
`contract_sweeper/runtime/`.

## 5. Dependency stack

`requirements.txt` declares: `pandas`, `requests`, `lxml`, `pytest`,
`rapidfuzz`, `python-dotenv`, `pyarrow`. **Adding in R5**: `PyYAML`,
`networkx`. Optional: `pydantic` deferred.

`.env.example` declares: `SAM_API_KEY`, `LDA_API_KEY`, `FEC_API_KEY`,
`OPENCORPORATES_API_TOKEN`. **Adding in R5**: `HGOV_API_KEY`, `FELT_API_KEY`.

`pytest.ini` markers: `unit`, `integration`, `pipeline_gate`,
`non_executing`, `external`, `slow`.

`Contract-Sweeper-Secrets/` (sibling, outside repo) holds `SAM_API_KEY.txt`,
`LDA_API_KEY.txt`, `HGOV_API_KEY.txt`, `FELT_API_KEY.txt`. **Never read or
print these values**.

## 6. Data layer

- `data/raw/`: HigherGov PDFs (4), LDA outputs, Oficina del Contralor, USAS
  evidence + API mirror, Donaciones CSV (840KB), `pr_all_awards_master.csv`,
  fixtures for FEC/Grants/SAM/cdbg_dr/sba/slfrf/subawards.
  - `data/raw/fema_pa/` is empty. `data/raw/SAM/` has only `test_sam.py`.
- `data/staging/`: 1,125 files across `expansion/`, `processed/`, `raw/`. Many
  r4_8/r4_9 snapshots.
- `data/exports/`: 96 r4_X recovery artifacts; **none of the canonical mission
  outputs**.
- `data/manifests/`: subfolders `r4_8d/` (8 files) and `r4_9g/` (5 files).
  Sample schema:
  ```
  generated_at, known_gaps, manifest_type, producer_script,
  row_count, schema_version, sha256, source_file, source_system,
  target_output_path, validation_status
  ```
  **Missing fields vs mission spec**: `year_coverage_pct`,
  `field_completeness_pct_by_column`, `entity_match_rate_pct`,
  `ingestion_timestamp_utc`, `source_url`,
  `unresolved_high_value_entities_count`. R5 `manifest_runtime.py` adds these.
- `data/review_queue/`: 80 r4_X-style blocker tracking CSVs (credentials,
  endpoints, manual-file requests, schema gaps). **None resemble the canonical
  `review_queue.csv`** (per-row, link_confidence-driven). Will be unified in PR2.
- `data/logs/`: 90+ download_/ingest_/pipeline_ logs.
- `data/reports/`: `pr_investigative_report.md`, `pr_report_summary.json`.

## 7. Test layer (`tests/`)

58 test files. All target backfill/freeze/recovery flows (R4.5 → R4.9Z-F).

**Missing canonical tests** (added in R5): `test_source_registry`,
`test_schema_registry`, `test_manifest_runtime`, `test_validation_gates`,
`test_name_normalization`, `test_linkage_confidence`, `test_no_secret_leakage`.

`pytest.ini` has the expected markers, and `tests/conftest.py` is configured.
`.pytest_cache/` exists but no lastfailed history was inspected during this
audit.

## 8. Docs layer (`docs/`)

19 docs, all about gates/freezes/blockers/runbooks
(`BLOCKED_PHASES_AND_UNFREEZE_RULES`, `CI_TESTING_STRATEGY`,
`CLAIM_LANGUAGE_POLICY`, `DEPENDENCY_SECURITY_AUDIT`,
`OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z`, `OUTPUT_CONTRACTS`,
`PRODUCTION_GATES`, `REFERENCE_ARCHITECTURES`, `SECRET_HANDLING_POLICY`,
`SOURCE_RECOVERY_RUNBOOK`, `TESTING_STRATEGY`, `WHEN_TO_RESUME_R4_9G`, etc.).

**Missing audit deliverables** (added in R5): `repo_audit.md` (this file),
`source_inventory.csv`, `missing_modules.md`, `broken_imports.md`,
`placeholder_detection.md`, `execution_roadmap.md`, `prioritized_patch_plan.md`,
`backfill_plan.md`.

## 9. CI

`.github/workflows/`:
- `ci.yml` — `python -m compileall contract_sweeper tests` + `pytest -q`.
- `tests.yml` — matrix Python 3.10/3.11/3.12; `pytest tests/ -v`.
- `production-status-gate.yml` — runs `scripts/run_production_status_gate.py`
  and enforces `data/exports/production_status.json` + `rebuild_status.json`.
- `highergov-fetch.yml` — fetches HigherGov.

**Missing in CI**: validation_gates step, secret_scan step. R5 adds both.

## 10. Sibling & worktree state

- `Contract-Sweeper-Secrets/`: 4 key files. Read-only.
- `Contract-Sweeper-worktrees/`: 13 worktrees, mostly empty stubs of historical
  phase work. Safe to leave; cleanup deferred.
- `Documents/Coding/Contract-Sweep/`: **the R5 foundation source**.
  Contains a working Contract Cradle hardening pass with
  `source_registry.py/.json`, `schema_registry.py/.json`, `manifest_runtime.py`,
  `validation_gates.py`, `parent_collapse.py`, `alias_registry_builder.py`,
  `execution_chain_builder.py`, `influence_graph_builder.py`,
  `quarantine_stale_outputs.py`, `contract_cradle_harden.py`. Modules are
  minimal (each <100 LOC) and already enforce the 0.95/0.90 thresholds. R5 PR1
  ports these and extends them.
- `Downloads/Local Coding/Contract-Sweep/`: snapshot with the same registries
  plus pre-computed audit artifacts. Useful cross-reference.
- `Documents/Coding/Contract-Sweer/` (typo): incomplete fork, drop later.
- `PR.INT/`, `Downloads/Local Coding/PR-INT/`: separate PR intelligence
  packages with their own pipelines. **Not** merged into Contract-Sweeper.

## 11. Branch state

Pre-R5 active branch was `codex/r4-10a-governance-and-promotion-guard` — opened
but no R4.10A commit yet. `origin/main` head = `c2b2356` ("Ignore local USAS
raw acquisition folder"). R5 work lands on a new branch
`claude/r5-source-registry-and-validation-gates` cut from `origin/main`.

---

## Summary

The repo has spent ~13 R4 iterations on backfill-recovery meta-orchestration
without producing any canonical mission output. The R5 takeover ports a
working foundation from a sibling repo and extends it to cover the full
40-source ecosystem with enforced validation gates, so PR2 onward can
materialize real data behind known thresholds.
