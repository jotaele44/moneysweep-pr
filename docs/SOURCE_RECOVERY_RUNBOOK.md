# Source Recovery Runbook

Use this runbook when an operator is trying to unpause source recovery after R4.9Z. It explains what must be acquired outside the repo, where it must be delivered, and what checks must pass before any retry phase is allowed.

## Operating Rules

1. Do not run download retries while `unfreeze_candidates` is `0`.
2. Do not ingest rows from newly delivered files until delivery validation passes.
3. Do not stage production inputs from unvalidated files.
4. Do not start R4.9G, R5, R6, R7, R8, R9, or R10 while the pause lock remains active.
5. Preserve `NON_PRODUCTION_DIAGNOSTIC` until production gates explicitly pass.
6. Preserve the Phase 7/8 block until downstream blockers are explicitly cleared by validated source coverage.

## Source State

Current source delivery blockers:

- Manual file deliveries required: `14`.
- Physical validated files missing: `7`.
- Total blockers: `21`.
- Unfreeze candidates: `0`.

The authoritative queues are:

- `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`
- `data/review_queue/source_delivery_checklist_r4_9e.csv`
- `data/review_queue/manual_files_still_required_r4_9c.csv`
- `data/review_queue/physical_validated_files_still_missing_r4_9c.csv`

## Column Profiles

Most rows use one of three required-column profiles. The authoritative required columns remain in `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`.

`contracts_master`:

```text
contract_id, vendor_name, agency_name, award_date, obligated_amount, pop_state, source_file, fiscal_year
```

`standard_awards_master`:

```text
award_id, recipient_name, recipient_name_normalized, recipient_uei, awarding_agency, awarding_sub_agency, obligated_amount, award_date, fiscal_year, pop_state, pop_county, description, source_file, source_dataset, award_category, source_system, source_record_id, source_lineage_path, source_lineage_mode
```

`expansion_awards`:

```text
Award ID, Recipient Name, Awarding Agency, Awarding Sub Agency, Total Obligation, Start Date, Place of Performance State Code, Place of Performance City, Description, generated_internal_id
```

## Validation

For each delivered source, run the exact `validation_command` from `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`. That command checks:

- target output exists;
- rows are nonzero;
- required columns are present.

Each accepted delivery also needs SHA256 computation and a validated manifest update before it can be treated as an unfreeze candidate.

After one or more files are delivered into an approved path, run only the watch and pause checks:

```bash
python scripts/run_source_delivery_watch_r49f.py --root .
python scripts/run_source_recovery_pause_lock_r49z.py --root .
```

Do not start R4.9G unless R4.9F reports `unfreeze_candidates > 0`.

## Manual Source Acquisition Checklist

For manual file deliveries, acquire or export the source outside the repo, save the file using the expected filename pattern, and place it in the exact dropzone. Do not run repo download scripts as a substitute for external delivery while the pause lock is active.

| Expected target | Source family | External acquisition instruction | Dropzone | Filename pattern | Column profile | Unfreeze condition |
| --- | --- | --- | --- | --- | --- | --- |
| `data/staging/processed/pr_contracts_master.csv` | `usaspending_federal_awards_backbone` | Export the Puerto Rico federal contract backbone from USAspending or an approved external USAspending export. | `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/pr_contracts_master.csv` | `pr_contracts_master.csv`, `pr_contracts_master*.csv`, or `*.csv` | `contracts_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_grants_master.csv` | `usaspending_federal_awards_backbone` | Export the Puerto Rico federal grants backbone from USAspending or an approved external USAspending export. | `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/pr_grants_master.csv` | `pr_grants_master.csv`, `pr_grants_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_subawards_master.csv` | `fsrs_subawards` | Export Puerto Rico FSRS subaward data from FSRS or an approved external FSRS export. | `data/manual_import_dropzone/r4_8e/fsrs_subawards/pr_subawards_master.csv` | `pr_subawards_master.csv`, `pr_subawards_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_fema_pa_master.csv` | `fema_pa_hmgp` | Export Puerto Rico FEMA Public Assistance records from OpenFEMA or an approved external FEMA export. | `data/manual_import_dropzone/r4_8e/fema_pa_hmgp/pr_fema_pa_master.csv` | `pr_fema_pa_master.csv`, `pr_fema_pa_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_fema_hmgp_master.csv` | `fema_pa_hmgp` | Export Puerto Rico FEMA HMGP records from OpenFEMA or an approved external FEMA export. | `data/manual_import_dropzone/r4_8e/fema_pa_hmgp/pr_fema_hmgp_master.csv` | `pr_fema_hmgp_master.csv`, `pr_fema_hmgp_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_research_master.csv` | `federal_research` | Export Puerto Rico federal research award records from NSF Award Search or an approved external research-award export. | `data/manual_import_dropzone/r4_8e/federal_research/pr_research_master.csv` | `pr_research_master.csv`, `pr_research_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_sba_loans_master.csv` | `sba_loans` | Export Puerto Rico SBA loan records from SBA or an approved external SBA export. | `data/manual_import_dropzone/r4_8e/sba_loans/pr_sba_loans_master.csv` | `pr_sba_loans_master.csv`, `pr_sba_loans_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_cdbg_dr_master.csv` | `hud_cdbg` | Export Puerto Rico HUD CDBG-DR records from HUD Exchange or an approved external HUD export. | `data/manual_import_dropzone/r4_8e/hud_cdbg/pr_cdbg_dr_master.csv` | `pr_cdbg_dr_master.csv`, `pr_cdbg_dr_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_sbir_master.csv` | `federal_sectoral_sbir` | Export Puerto Rico SBIR/STTR award records from SBIR.gov or an approved external SBIR export. | `data/manual_import_dropzone/r4_8e/federal_sectoral_sbir/pr_sbir_master.csv` | `pr_sbir_master.csv`, `pr_sbir_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/processed/pr_usace_civil_master.csv` | `federal_sectoral_usace` | Export Puerto Rico USACE civil works records from USACE or an approved external USACE export. | `data/manual_import_dropzone/r4_8e/federal_sectoral_usace/pr_usace_civil_master.csv` | `pr_usace_civil_master.csv`, `pr_usace_civil_master*.csv`, or `*.csv` | `standard_awards_master` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/expansion/expansion_idv_indirect_pr.csv` | `usaspending_federal_awards_backbone` | Export Puerto Rico IDV/indirect award expansion records from USAspending or an approved external USAspending export. | `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/expansion_idv_indirect_pr.csv` | `expansion_idv_indirect_pr.csv`, `expansion_idv_indirect_pr*.csv`, or `*.csv` | `expansion_awards` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/expansion/expansion_dod_upr_2001_2015.csv` | `usaspending_federal_awards_backbone` | Export Puerto Rico DoD UPR expansion records for 2001 through 2015 from USAspending or an approved external USAspending export. | `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/expansion_dod_upr_2001_2015.csv` | `expansion_dod_upr_2001_2015.csv`, `expansion_dod_upr_2001_2015*.csv`, or `*.csv` | `expansion_awards` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/expansion/expansion_dod_upr_2016_2025.csv` | `usaspending_federal_awards_backbone` | Export Puerto Rico DoD UPR expansion records for 2016 through 2025 from USAspending or an approved external USAspending export. | `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/expansion_dod_upr_2016_2025.csv` | `expansion_dod_upr_2016_2025.csv`, `expansion_dod_upr_2016_2025*.csv`, or `*.csv` | `expansion_awards` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |
| `data/staging/expansion/expansion_reconstruction_2017_2025.csv` | `usaspending_federal_awards_backbone` | Export Puerto Rico reconstruction expansion records for 2017 through 2025 from USAspending or an approved external USAspending export. | `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/expansion_reconstruction_2017_2025.csv` | `expansion_reconstruction_2017_2025.csv`, `expansion_reconstruction_2017_2025*.csv`, or `*.csv` | `expansion_awards` | File delivered, required columns present, nonzero rows, SHA256 computed, validated manifest written. |

## Physical Validated Source Restoration Checklist

For physical validated file restorations, restore the validated physical file at the target output path listed below. There is no manual dropzone in the current checklist for these rows. The restored file must match the relevant manifest expectation and pass the row/schema/hash checks before it can unfreeze anything.

| Target output | Source family | Manifest reference | Delivery instruction | Column profile | Unfreeze condition |
| --- | --- | --- | --- | --- | --- |
| `data/staging/processed/pr_doe_master.csv` | `federal_sectoral_doe` | `data/manifests/r4_8d/12_pr_doe_master.manifest.json` | Restore the validated DOE physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |
| `data/staging/processed/pr_dot_master.csv` | `federal_sectoral_dot` | `data/manifests/r4_8d/10_pr_dot_master.manifest.json` | Restore the validated DOT physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |
| `data/staging/processed/pr_epa_master.csv` | `federal_sectoral_epa` | `data/manifests/r4_8d/15_pr_epa_master.manifest.json` | Restore the validated EPA physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |
| `data/staging/processed/pr_hud_master.csv` | `hud_cdbg` | `data/manifests/r4_8d/13_pr_hud_master.manifest.json` | Restore the validated HUD physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |
| `data/staging/processed/pr_slfrf_master.csv` | `slfrf` | `data/manifests/r4_8d/08_pr_slfrf_master.manifest.json` | Restore the validated SLFRF physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |
| `data/staging/processed/pr_usda_master.csv` | `federal_sectoral_usda` | `data/manifests/r4_8d/11_pr_usda_master.manifest.json` | Restore the validated USDA physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |
| `data/staging/processed/pr_wioa_grants.csv` | `federal_sectoral_wioa` | `data/manifests/r4_8d/17_pr_wioa_grants.manifest.json` | Restore the validated WIOA physical source file to the target path. | `standard_awards_master` | File exists at target path, manifest-compatible hash, required columns present, nonzero rows, validated manifest written. |

## Operator Checklist

1. Confirm there is an actual external change: a file was delivered, an approved access credential was changed, or an endpoint/export path was fixed outside the repo.
2. Confirm the delivered file is in the approved dropzone or target output path for that source.
3. Confirm the filename matches the accepted pattern for manual deliveries.
4. Run the per-source `validation_command` from `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`.
5. Compute SHA256 and write or update the validated source manifest for the accepted delivery.
6. Run `python scripts/run_source_delivery_watch_r49f.py --root .`.
7. Run `python scripts/run_source_recovery_pause_lock_r49z.py --root .`.
8. Start R4.9G only if R4.9F reports `unfreeze_candidates > 0`.
9. Keep R5 through R10 blocked until source coverage and the diagnostic rebuild explicitly support downstream progression.

