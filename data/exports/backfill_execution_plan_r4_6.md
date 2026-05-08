# R4.6 Backfill Execution Plan

Generated: 2026-05-08T14:39:19Z

## Guardrails

- No fabricated/synthetic rows are allowed.
- Only raw/staging/normalized/exports/runtime sources may be used for recovery planning.
- Report/summary/graph/top-node artifacts are not valid data inputs.
- Phase 7/8 remains blocked until recovery and downstream validation gates pass.

## Inputs To Backfill

### 1. `data/staging/processed/pr_contracts_master.csv`
- Dataset: `contracts` (core)
- Source of truth: USASpending/FPDS normalized expansion files
- Producer script: `scripts/deduplicate_master.py`
- Command: `python scripts/deduplicate_master.py`
- Precheck: normalized_expansion_*.csv available in data/staging/processed
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 2. `data/staging/processed/pr_grants_master.csv`
- Dataset: `grants` (canonical_master)
- Source of truth: USASpending assistance/grants APIs
- Producer script: `scripts/download_grants.py`
- Command: `python scripts/download_grants.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 3. `data/staging/processed/pr_subawards_master.csv`
- Dataset: `subawards` (canonical_master)
- Source of truth: FSRS/Subawards feeds
- Producer script: `scripts/download_subawards.py`
- Command: `python scripts/download_subawards.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 4. `data/staging/processed/pr_fema_pa_master.csv`
- Dataset: `fema_pa` (canonical_master)
- Source of truth: OpenFEMA Public Assistance datasets
- Producer script: `scripts/download_fema.py`
- Command: `python scripts/download_fema.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 5. `data/staging/processed/pr_fema_hmgp_master.csv`
- Dataset: `fema_hmgp` (canonical_master)
- Source of truth: OpenFEMA HMGP datasets
- Producer script: `scripts/download_fema.py`
- Command: `python scripts/download_fema.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 6. `data/staging/processed/pr_research_master.csv`
- Dataset: `research` (canonical_master)
- Source of truth: Federal research award sources
- Producer script: `scripts/download_research.py`
- Command: `python scripts/download_research.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 7. `data/staging/processed/pr_sba_loans_master.csv`
- Dataset: `sba_loans` (canonical_master)
- Source of truth: SBA disaster/business loan datasets
- Producer script: `scripts/download_sba.py`
- Command: `python scripts/download_sba.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 8. `data/staging/processed/pr_slfrf_master.csv`
- Dataset: `slfrf` (canonical_master)
- Source of truth: Treasury SLFRF recipient project files
- Producer script: `scripts/download_slfrf.py`
- Command: `python scripts/download_slfrf.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 9. `data/staging/processed/pr_cdbg_dr_master.csv`
- Dataset: `cdbg_dr` (canonical_master)
- Source of truth: HUD CDBG-DR / DRGR exports
- Producer script: `scripts/download_cdbg_dr.py`
- Command: `python scripts/download_cdbg_dr.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 10. `data/staging/processed/pr_dot_master.csv`
- Dataset: `dot` (canonical_master)
- Source of truth: DOT award datasets
- Producer script: `scripts/download_dot.py`
- Command: `python scripts/download_dot.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 11. `data/staging/processed/pr_usda_master.csv`
- Dataset: `usda` (canonical_master)
- Source of truth: USDA award datasets
- Producer script: `scripts/download_usda.py`
- Command: `python scripts/download_usda.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 12. `data/staging/processed/pr_doe_master.csv`
- Dataset: `doe` (canonical_master)
- Source of truth: DOE award datasets
- Producer script: `scripts/download_doe.py`
- Command: `python scripts/download_doe.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 13. `data/staging/processed/pr_hud_master.csv`
- Dataset: `hud` (canonical_master)
- Source of truth: HUD federal award datasets
- Producer script: `scripts/download_hud.py`
- Command: `python scripts/download_hud.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 14. `data/staging/processed/pr_sbir_master.csv`
- Dataset: `sbir` (canonical_master)
- Source of truth: SBIR/STTR award datasets
- Producer script: `scripts/download_sbir.py`
- Command: `python scripts/download_sbir.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 15. `data/staging/processed/pr_epa_master.csv`
- Dataset: `epa` (canonical_master)
- Source of truth: EPA award datasets
- Producer script: `scripts/download_epa.py`
- Command: `python scripts/download_epa.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 16. `data/staging/processed/pr_usace_civil_master.csv`
- Dataset: `usace_civil` (canonical_master)
- Source of truth: USACE civil works award datasets
- Producer script: `scripts/download_usace_civil.py`
- Command: `python scripts/download_usace_civil.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 17. `data/staging/processed/pr_wioa_grants.csv`
- Dataset: `wioa` (canonical_master)
- Source of truth: WIOA grants datasets
- Producer script: `scripts/download_wioa.py`
- Command: `python scripts/download_wioa.py --force`
- Precheck: raw/staging source files present OR downloader credentials configured
- Acceptance gate: file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 18. `data/staging/expansion/expansion_idv_indirect_pr.csv`
- Dataset: `contracts` (expansion)
- Source of truth: USASpending expansion extracts (IDV/DoD/reconstruction windows)
- Producer script: `scripts/config.py`
- Command: `python run_all.py --only usaspending --force`
- Precheck: USASpending credentials/config ready; extraction windows configured
- Acceptance gate: file_exists AND rows>0 AND lineage_manifest_present AND window_coverage_verified
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 19. `data/staging/expansion/expansion_dod_upr_2001_2015.csv`
- Dataset: `contracts` (expansion)
- Source of truth: USASpending expansion extracts (IDV/DoD/reconstruction windows)
- Producer script: `scripts/config.py`
- Command: `python run_all.py --only usaspending --force`
- Precheck: USASpending credentials/config ready; extraction windows configured
- Acceptance gate: file_exists AND rows>0 AND lineage_manifest_present AND window_coverage_verified
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 20. `data/staging/expansion/expansion_dod_upr_2016_2025.csv`
- Dataset: `contracts` (expansion)
- Source of truth: USASpending expansion extracts (IDV/DoD/reconstruction windows)
- Producer script: `scripts/config.py`
- Command: `python run_all.py --only usaspending --force`
- Precheck: USASpending credentials/config ready; extraction windows configured
- Acceptance gate: file_exists AND rows>0 AND lineage_manifest_present AND window_coverage_verified
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`

### 21. `data/staging/expansion/expansion_reconstruction_2017_2025.csv`
- Dataset: `contracts` (expansion)
- Source of truth: USASpending expansion extracts (IDV/DoD/reconstruction windows)
- Producer script: `scripts/config.py`
- Command: `python run_all.py --only usaspending --force`
- Precheck: USASpending credentials/config ready; extraction windows configured
- Acceptance gate: file_exists AND rows>0 AND lineage_manifest_present AND window_coverage_verified
- Fabrication policy: `FORBIDDEN_NO_SYNTHETIC_ROWS`
