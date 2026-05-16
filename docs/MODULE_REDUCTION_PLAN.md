# Module Reduction Plan

**Date:** 2026-05-15  
**Branch:** `claude/module-reduction-cleanup-ogfpf`  
**Test status:** 594 passed · 4 skipped · 0 failed (10.1 s)

---

## Summary

| Before | After (estimate) | Delta |
|--------|-----------------|-------|
| 228 modules | ~162 modules | **−66 files (−29%)** |
| 80,308 lines | ~71,100 lines | **−9,200 lines** |

Inventory: `module_inventory.csv` (225 rows)  
Machine-readable status: `current_status.json`

---

## Category Definitions

| Label | Meaning |
|-------|---------|
| **KEEP** | Retain as-is — unique logic, high import count, or has tests |
| **MERGE** | Consolidate into a named target module |
| **ARCHIVE** | Move to `archive/` — stale, dev-only, or superseded; do not import |
| **DELETE** | Remove — micro-module with logic trivially inline-able into its parent |

---

## KEEP (151 modules)

All modules not listed below are **KEEP**. High-value anchors:

| Module | Why keep |
|--------|---------|
| `scripts/config.py` | 121 inbound imports — foundational config hub |
| `scripts/build_unified_master.py` | 25 inbound imports — core ETL entrypoint |
| `contract_sweeper/pipeline/acquisition_package.py` | 18 inbound imports |
| `scripts/parquet_utils.py` | 13 inbound imports — I/O utility hub |
| `contract_sweeper/validation/production_status.py` | 8 inbound imports |
| `scripts/sam_enrichment.py` | 6 inbound imports; tested |
| `run_all.py` | Main orchestrator (2,288 lines) |
| All `download_*.py` (74 files) | Unique per-source download logic |

---

## MERGE (62 modules → 13 targets)

### Group 1 — Pipeline CLI wrappers → `scripts/run_pipeline.py`
**29 files → 1 file (saves 28 files)**

Every `scripts/run_*.py` is a ≤80-line argparse wrapper around exactly one pipeline module.  
Consolidate into a single `run_pipeline.py` with a `--step` / `--module` subcommand dispatch table.

Files to merge:
```
scripts/run_acquisition_package_r48g.py
scripts/run_artifact_lineage_audit.py
scripts/run_backfill_execution_plan_r46.py
scripts/run_backfill_failure_remediation_r48c.py
scripts/run_backfill_readiness_audit_r48a.py
scripts/run_backfill_runner_r47.py
scripts/run_controlled_backfill_execution_r48b.py
scripts/run_controlled_backfill_r48.py
scripts/run_entity_universe_audit.py
scripts/run_external_blocker_freeze_r49d.py
scripts/run_external_source_delivery_gate_r49c.py
scripts/run_final_source_recovery_pass_r48i.py
scripts/run_manual_fallback_endpoint_resolution_r48e.py
scripts/run_manual_fulfillment_endpoint_retry_r48h.py
scripts/run_manual_import_dropzone_retry_r48f.py
scripts/run_master_input_recovery_and_rebuild.py
scripts/run_partial_master_rebuild_r49a.py
scripts/run_production_status_gate.py
scripts/run_raw_usaspending_discovery_r49h.py
scripts/run_raw_usaspending_mapping_feasibility_r49h2.py
scripts/run_repo_quality_audit_r49z_b.py
scripts/run_scoped_unfreeze_retry_r49g.py
scripts/run_source_coverage_audit.py
scripts/run_source_delivery_handoff_r49e.py
scripts/run_source_delivery_watch_r49f.py
scripts/run_source_input_recovery_and_canonical_staging.py
scripts/run_source_materialization_rebuild_retry_r49b.py
scripts/run_source_recovery_pause_lock_r49z.py
scripts/run_targeted_backfill_retry_r48d.py
```

---

### Group 2 — PR local-source ingesters → `scripts/ingest_pr_local_sources.py`
**5 files → 1 file (saves 4 files)**

All five ingest Puerto Rico government data (contractors, lobbyists, comptroller, PRASA, COR3) with identical 9-function structure.

```
scripts/ingest_active_contractors.py
scripts/ingest_cabilderos.py
scripts/ingest_contralor.py
scripts/ingest_cor3.py
scripts/ingest_prasa.py
```

---

### Group 3 — CMS sub-program downloaders → `scripts/download_cms_programs.py`
**4 files → 1 file (saves 3 files)**

Medicare Advantage, Medicare Parts A/B/D, Medicaid FMAP, and CHIP are all CMS sub-programs with homogeneous download logic.

```
scripts/download_chip.py
scripts/download_medicaid_fmap.py
scripts/download_medicare_advantage.py
scripts/download_medicare_parts.py
```

---

### Group 4 — Source mappers → `scripts/source_mappers.py`
**4 files → 1 file (saves 3 files)**

All four mapper files are identical in structure: a `*_MAPPINGS` dict + a three-function apply/validate/normalize API.

```
scripts/cms_mapper.py
scripts/emma_mapper.py
scripts/fdic_mapper.py
scripts/highergov_mapper.py
```

---

### Group 5 — Asset linkers → `scripts/asset_linkers.py`
**3 files → 1 file (saves 2 files)**

All three read normalized parquets and write `data/linked/*.csv`. Consolidate under named functions.

```
scripts/link_fema_pa_to_contracts.py
scripts/link_hud_drgr_to_assets.py
scripts/link_hud_drgr_to_contracts.py
```

---

### Group 6 — Disaster-funding validators → `scripts/validate_disaster_funding.py`
**3 files → 1 file (saves 2 files)**

FEMA PA coverage + HUD DRGR amounts + HUD DRGR coverage are all disaster-recovery funding validators.

```
scripts/validate_fema_pa_coverage.py
scripts/validate_hud_drgr_amounts.py
scripts/validate_hud_drgr_coverage.py
```

---

### Group 7 — Crossref analyzers → `scripts/analyze_crossref.py`
**2 files → 1 file (saves 1 file)**

Both crossref scripts load entity master + a secondary source and produce a match/gap report.

```
scripts/analyze_fec_crossref.py
scripts/analyze_lobbying_crossref.py
```

---

### Group 8 — Input normalizers → `scripts/normalize_inputs.py`
**2 files → 1 file (saves 1 file)**

```
scripts/normalize_expansion_inputs.py
scripts/normalize_hud_drgr.py
```

---

### Group 9 — Disaster-recovery ingesters → `scripts/ingest_disaster_recovery.py`
**2 files → 1 file (saves 1 file)**

```
scripts/ingest_fema_pa_portal_exports.py
scripts/ingest_hud_drgr_exports.py
```

---

### Group 10 — Pipeline schema management → `contract_sweeper/pipeline/schema_management.py`
**2 files → 1 file (saves 1 file)**

Schema alignment and schema remediation are two phases of the same operation.

```
contract_sweeper/pipeline/schema_alignment.py
contract_sweeper/pipeline/schema_remediation.py
```

---

### Group 11 — Endpoint management → `contract_sweeper/pipeline/endpoint_management.py`
**2 files → 1 file (saves 1 file)**

```
contract_sweeper/pipeline/endpoint_patch_retry.py
contract_sweeper/pipeline/endpoint_resolution.py
```

---

### Group 12 — Producer management → `contract_sweeper/pipeline/producer_management.py`
**2 files → 1 file (saves 1 file)**

```
contract_sweeper/pipeline/producer_failure_resolution.py
contract_sweeper/pipeline/producer_patch_retry.py
```

---

## ARCHIVE (11 modules)

Move to `archive/` — do not delete (may contain reference logic), but remove from active imports.

| Module | Reason |
|--------|--------|
| `data/raw/SAM/test_sam.py` | Stray test file outside `tests/`; belongs in `tests/` or deleted |
| `scripts/highergov_manifest.py` | 39-line data-only stub (0 functions); superseded by `source_registry` |
| `scripts/fetch_highergov_api.py` | 102 lines; superseded by `parse_highergov_pdfs` + full API integration |
| `scripts/dominance_analysis.py` | Standalone market-concentration analysis; no tests; not wired into `run_all` |
| `scripts/analyze_prime_sub.py` | Standalone analysis; no tests; not wired into pipeline |
| `scripts/triage_misc_drop.py` | One-off triage; no tests; not referenced |
| `scripts/scan_for_secrets.py` | Dev tooling; not in CI; no tests |
| `scripts/regenerate_registry_json.py` | Dev utility; 0 inbound imports; no tests |
| `scripts/parse_highergov_pdfs.py` | One-time PDF parser; no tests; 0 inbound refs |
| `contract_sweeper/validation/cache_audit.py` | Audit artifact; no tests; low active usage |
| `contract_sweeper/pipeline/credential_unblock_plan.py` | Planning artifact; 1 import; no tests |

---

## DELETE (6 modules)

Remove entirely — all logic is trivially inlinable into the consuming module.

| Module | Lines | Inline into |
|--------|-------|-------------|
| `contract_sweeper/pipeline/partial_rebuild_gate.py` | 26 | `partial_master_rebuild.py` |
| `contract_sweeper/pipeline/unfreeze_guard.py` | 71 | `scoped_unfreeze_materialization.py` |
| `contract_sweeper/pipeline/manual_fulfillment_execution.py` | 60 | `manual_import_dropzone.py` |
| `contract_sweeper/pipeline/import_slots.py` | 67 | `backfill_runner.py` |
| `contract_sweeper/runtime/file_hash_runtime.py` | 16 | `manifest_runtime.py` |
| `contract_sweeper/runtime/pagination_runtime.py` | 45 | Delete (0 external consumers) |

---

## Top Consolidation Targets (Ranked by Impact)

| Rank | Action | Files Before | Files After | Δ Files | Estimated Δ Lines |
|------|--------|-------------|------------|---------|-------------------|
| 1 | Merge `run_*.py` → `run_pipeline.py` | 29 | 1 | **−28** | −1,920 |
| 2 | Merge PR local ingesters | 5 | 1 | **−4** | −760 |
| 3 | Delete pipeline micro-modules | 6 | 0 | **−6** | −285 |
| 4 | Merge CMS sub-program downloaders | 4 | 1 | **−3** | −820 |
| 5 | Merge source mappers | 4 | 1 | **−3** | −440 |
| 6 | Merge asset linkers | 3 | 1 | **−2** | −610 |
| 7 | Merge disaster-funding validators | 3 | 1 | **−2** | −590 |
| 8 | Merge crossref analyzers | 2 | 1 | **−1** | −370 |
| 9 | Merge schema management | 2 | 1 | **−1** | −370 |
| **Total top 9** | | **58** | **8** | **−50** | **−6,165** |

---

## Implementation Order

Execute in this sequence to keep tests green at each step:

1. **DELETE** the 6 micro-modules (inline their logic first, update all imports, re-run pytest)
2. **MERGE** source_mappers (4→1) — lowest risk, mappers have tests
3. **MERGE** asset_linkers, normalize_inputs, analyze_crossref (small groups)
4. **MERGE** ingest_pr_local_sources, ingest_disaster_recovery
5. **MERGE** download_cms_programs, validate_disaster_funding
6. **MERGE** pipeline module pairs (schema_management, endpoint_management, producer_management)
7. **MERGE** run_pipeline.py (biggest win; do last to avoid breaking any CI that calls individual run_* scripts by name)
8. **ARCHIVE** the 11 modules (move files, remove from imports)

Run `pytest tests/ -q` after each step.
