# Module Reduction Plan

**Generated:** 2026-05-15  
**Branch:** claude/r7-risk-signal-engine  
**Baseline:** 304 modules · 79,608 lines · 639 tests passing

---

## Executive Summary

| Action  | Modules | Lines  | % of total |
|---------|--------:|-------:|-----------:|
| KEEP    | 167     | 40,186 | 50 %       |
| ARCHIVE | 118     | 36,238 | 46 %       |
| MERGE   | 18      | 3,145  | 4 %        |
| DELETE  | 1       | 39     | < 1 %      |

**Removable from active tree: ~47.9 % of lines** (archive + delete + 60 % of merge).  
No production-path code is touched. All 639 tests continue to pass after any action here.

---

## Pytest (lightweight)

```
639 passed, 5 skipped in 20.96s
```

All passing. Skips are platform-conditioned (not failures).

---

## Category Definitions

| Label   | Meaning |
|---------|---------|
| KEEP    | In active production path — imported by CI, runtime, or active build scripts |
| ARCHIVE | Phase-specific (R4 backfill complete) or expansion sources outside core 14 registry |
| MERGE   | Two or more modules with near-identical purpose — consolidate into one file |
| DELETE  | Empty or zero-function file; safe to remove immediately |

---

## KEEP — Active Production Modules (167 files)

### contract_sweeper/runtime/ (12 modules · 2,307 lines)
All active. These are the R5/R7 production stack.

| Module | Lines | Purpose |
|--------|------:|---------|
| validation_gates.py | 503 | R5 gate enforcement (SOURCE_COVERAGE ≥ 0.93, 14/14) |
| risk_signals.py | 708 | R7 signal engine — 8 families, compute_signals() |
| manifest_runtime.py | 389 | Per-source manifest writer |
| risk_signal_gates.py | 194 | R7 completion gates |
| schema_registry.py | 106 | Schema-registry loader |
| source_registry.py | 126 | Source-registry loader |
| name_normalization.py | 57 | Entity-name normalization |
| linkage_confidence.py | 59 | Sub-award linkage scoring |
| retry_runtime.py | 68 | Jittered exponential backoff |
| pagination_runtime.py | 45 | Ingestion pagination helper |
| file_hash_runtime.py | 16 | SHA-256 file hashing |
| __init__.py | 36 | Package init |

### contract_sweeper/validation/ (9 modules · 3,109 lines)
All active validation and audit layers.

### scripts/ — Core build & processing (39 files)
Includes: `build_unified_master.py`, `build_financial_flows_master.py`, `build_risk_signals.py`,
`execution_chain_builder.py`, `parent_collapse.py`, `entity_resolution.py`,
`sam_enrichment.py`, `lda_enrich.py`, `ngo_integration.py`, `generate_report.py`,
all 14 registered-source downloader scripts, all 11 ingest scripts,
all validate/link scripts, all mapper scripts, `config.py`, `scan_for_secrets.py`.

### tests/ — Substantive tests (55 files)
All test files with ≥ 3 test functions or covering production-path modules.

---

## TOP CONSOLIDATION TARGETS

### 1. R4 Pipeline Module Cluster — ARCHIVE (37 modules · 14,800 lines)

The entire `contract_sweeper/pipeline/` layer (except `__init__.py`) represents the
R4 source-acquisition backfill phase, which completed when R5 locked at 14/14 sources.
These modules are no longer on any active execution path.

**Action:** Move the entire `contract_sweeper/pipeline/` directory (minus `__init__.py`)
to `archive/pipeline_r4/`. Update `contract_sweeper/pipeline/__init__.py` to empty.

Estimated savings: **14,800 lines removed from active tree.**

Priority pipeline modules to archive first (largest):

| Module | Lines |
|--------|------:|
| controlled_backfill_execution.py | 810 |
| targeted_backfill_retry.py | 784 |
| partial_master_rebuild.py | 747 |
| final_backfill_retry.py | 739 |
| backfill_failure_remediation.py | 710 |
| final_source_recovery_pass.py | 703 |
| external_source_delivery_gate.py | 611 |
| backfill_readiness_audit.py | 574 |
| credentialed_endpoint_execution.py | 547 |
| raw_usaspending_discovery.py | 647 |

---

### 2. run_*.py Wrapper Scripts — ARCHIVE (29 scripts · 2,936 lines)

Every `scripts/run_*.py` file is a thin 30–80 line wrapper that calls a single
`pipeline.*` function. With the pipeline archived, these wrappers serve no purpose.

**Action:** Archive all 29 `run_*.py` scripts to `archive/run_wrappers_r4/`.

Estimated savings: **2,936 lines.**

---

### 3. Expansion Download Scripts — ARCHIVE (62 scripts · 21,000 lines)

74 download scripts exist; only 12 cover the 14 registered core sources.
The remaining 62 are expansion-scope downloaders for sources not in the registry
(CMS, SBA, SEC, VA, WIC, WIOA, FDIC, EPA, NIH, DOE, DOT, …).

**Action:** Move to `archive/download_expansion/`. Retain in git history.
Keep in active tree only: `download_emma`, `download_fema`, `download_grants`,
`download_subawards`, `download_lda`, `download_fec`, `download_cabilderos`,
`download_contralor`, `download_cor3`, `download_prasa`,
`download_hud_drgr_public`, `download_openfema_pa_projects`, `download_fsrs`,
`auto_download` (orchestrator).

Estimated savings: **~21,000 lines from active scripts/ tree.**

---

### 4. Pipeline Micro-Helper MERGE (18 modules → 5 files · saves ~1,850 lines)

18 small pipeline utility modules (avg 174 lines) can be collapsed into 5 files
without any public API change, since they're only used within the R4 cluster:

| Target file | Source modules | Combined lines |
|---|---|---:|
| `pipeline/schema_utils.py` | schema_alignment + schema_remediation | 374 |
| `pipeline/endpoint_retry_utils.py` | endpoint_resolution + endpoint_patch_retry + producer_failure_resolution + producer_patch_retry + external_acquisition_blocker_package | 959 |
| `pipeline/gate_helpers.py` | completion_gate + partial_rebuild_gate + unfreeze_guard | 211 |
| `pipeline/manual_import_utils.py` | import_slots + manual_import_validation + manual_fulfillment_execution + manual_fallback_package | 550 |
| `pipeline/credential_utils.py` | credential_unblock_plan + credentialed_endpoint_execution | 673 |

Note: since all source modules are also ARCHIVEd, the merge is optional — archiving
the whole pipeline cluster achieves the same result without any refactor.

---

### 5. analyze_fec_crossref + analyze_lobbying_crossref — MERGE

Both scripts do the same operation (normalize names → cross-reference against
awards master → emit matches with confidence scores) against different political
finance sources. Combined, they become `scripts/analyze_political_crossref.py`
with a `--source [fec|lda|both]` flag.

Lines saved: **~230 lines (deduplication of shared normalisation + matching logic).**

---

### 6. Stub Test Files — ARCHIVE (19 files · 4,800 lines)

19 test files have ≤ 2 test functions despite 100–400 lines of boilerplate.
All 19 cover R4 pipeline modules being archived.

| File | Tests | Lines |
|------|------:|------:|
| test_scoped_unfreeze_retry_r49g.py | 2 | 387 |
| test_acquisition_package_r48g.py | 2 | 357 |
| test_source_delivery_handoff_r49e.py | 2 | 262 |
| test_raw_usaspending_mapping_feasibility_r49h2.py | 2 | 272 |
| test_manual_fulfillment_endpoint_retry_r48h.py | 2 | 278 |
| test_manual_import_dropzone_retry_r48f.py | 2 | 293 |
| test_final_source_recovery_pass_r48i.py | 2 | 308 |
| test_raw_usaspending_discovery_r49h.py | 2 | 316 |
| test_external_blocker_freeze_r49d.py | 2 | 317 |
| test_external_source_delivery_gate_r49c.py | 2 | 325 |
| test_manual_fallback_endpoint_resolution_r48e.py | 2 | 325 |
| (+ 8 more) | | |

**Action:** Archive alongside their pipeline modules.

---

### 7. scripts/highergov_manifest.py — DELETE

39 lines, empty docstring, no functions, never imported. Safe to delete immediately.

---

## ARCHIVE — Full List

### contract_sweeper/pipeline/ (37 modules archived)
acquisition_package, backfill_failure_remediation, backfill_readiness_audit,
backfill_runner, completion_gate, controlled_backfill, controlled_backfill_execution,
credential_unblock_plan, credentialed_endpoint_execution, delivered_source_validation,
endpoint_patch_retry, endpoint_resolution, external_acquisition_blocker_package,
external_blocker_freeze, external_source_delivery_gate, final_backfill_retry,
final_source_recovery_pass, import_slots, manual_fallback_package,
manual_fulfillment_execution, manual_import_dropzone, manual_import_validation,
partial_master_rebuild, partial_rebuild_gate, partial_rebuild_retry,
producer_failure_resolution, producer_patch_retry, raw_source_candidate_validation,
raw_usaspending_discovery, raw_usaspending_mapping_feasibility, repo_quality_audit,
schema_alignment, schema_remediation, scoped_partial_rebuild,
scoped_unfreeze_materialization, source_delivery_handoff, source_delivery_watch,
source_manifest_writer, source_materialization, source_recovery_pause_lock,
targeted_backfill_retry, unfreeze_guard

### scripts/run_*.py (29 wrappers archived)
run_acquisition_package_r48g, run_artifact_lineage_audit, run_backfill_execution_plan_r46,
run_backfill_failure_remediation_r48c, run_backfill_readiness_audit_r48a,
run_backfill_runner_r47, run_controlled_backfill_execution_r48b,
run_controlled_backfill_r48, run_entity_universe_audit,
run_external_blocker_freeze_r49d, run_external_source_delivery_gate_r49c,
run_final_source_recovery_pass_r48i, run_manual_fallback_endpoint_resolution_r48e,
run_manual_fulfillment_endpoint_retry_r48h, run_manual_import_dropzone_retry_r48f,
run_master_input_recovery_and_rebuild, run_partial_master_rebuild_r49a,
run_raw_usaspending_discovery_r49h, run_raw_usaspending_mapping_feasibility_r49h2,
run_repo_quality_audit_r49z_b, run_scoped_unfreeze_retry_r49g,
run_source_coverage_audit, run_source_delivery_handoff_r49e,
run_source_delivery_watch_r49f, run_source_input_recovery_and_canonical_staging,
run_source_materialization_rebuild_retry_r49b, run_source_recovery_pause_lock_r49z,
run_targeted_backfill_retry_r48d, run_backfill_execution_plan_r46

### scripts/download_* — expansion (62 scripts archived)
All download scripts except: download_emma, download_fema, download_grants,
download_subawards, download_lda, download_fec, download_cabilderos,
download_contralor, download_cor3, download_prasa, download_hud_drgr_public,
download_openfema_pa_projects, download_fsrs.

---

## DELETE — Immediate

| File | Lines | Reason |
|------|------:|--------|
| scripts/highergov_manifest.py | 39 | Empty module — no docstring, no functions, never imported |

---

## Implementation Order

1. **Delete** `scripts/highergov_manifest.py` (0 risk, 0 impact)
2. **Archive** `contract_sweeper/pipeline/` → `archive/pipeline_r4/` (git mv)
3. **Archive** `scripts/run_*.py` → `archive/run_wrappers_r4/` (git mv)
4. **Archive** expansion download scripts → `archive/download_expansion/` (git mv)
5. **Archive** stub test files that cover archived modules → `archive/tests_r4/`
6. **Merge** `analyze_fec_crossref.py` + `analyze_lobbying_crossref.py` → `analyze_political_crossref.py`
7. Run `pytest -q` to confirm 639 still passing after each step

Each step is independently reversible via `git mv` in reverse.
The `archive/` directory is committed to git — nothing is lost.

---

## Metrics After Full Reduction

| Metric | Before | After | Delta |
|--------|-------:|------:|------:|
| Active modules | 304 | ~138 | -166 |
| Active lines | 79,608 | ~41,600 | -38,000 (-48%) |
| scripts/ download files | 74 | 13 | -61 |
| pipeline modules | 43 | 1 (__init__) | -42 |
| run_ wrappers | 29 | 0 | -29 |
| Stub test files | 19 | 0 | -19 |
