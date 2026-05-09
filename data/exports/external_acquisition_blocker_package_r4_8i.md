# R4.8I External Acquisition Blocker Package

- Generated at: `2026-05-09T01:00:20Z`
- Total unresolved blockers: `25`
- Manual file blockers: `14`
- Endpoint blockers: `9`
- Producer blockers: `2`

These blockers remain outside Codex control and require external file delivery, endpoint availability, and/or source access changes.

## Blockers

| Priority | Type | Source | Expected Input | Required Action | Reason |
|---:|---|---|---|---|---|
| 1 | manual_file_required | usaspending_federal_awards_backbone | data/staging/processed/pr_contracts_master.csv | Provide validated manual file in dropzone | no_file_present |
| 2 | endpoint_blocked | usaspending_federal_awards_backbone | data/staging/processed/pr_grants_master.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 2 | manual_file_required | usaspending_federal_awards_backbone | data/staging/processed/pr_grants_master.csv | Provide validated manual file in dropzone | no_file_present |
| 3 | manual_file_required | fsrs_subawards | data/staging/processed/pr_subawards_master.csv | Provide validated manual file in dropzone | no_file_present |
| 3 | producer_blocked | fsrs_subawards | data/staging/processed/pr_subawards_master.csv | Resolve producer failure and retry | 2026-05-08 21:00:13 [INFO] Starting PR subawards download... 2026-05-08 21:00:13 [INFO] [Window 2000f2009] 2007-10-01 to 2009-09-30 2026-05-08 21:00:13 [INFO] Fetching subawards_grants_2000f2009.csv (2007-10-01 to 2009-09-30, type=grants) 2026-05-08 21:00:14 [WARNING] No results for subawards_grants_2000f2009.csv 2026- |
| 4 | endpoint_blocked | fema_pa_hmgp | data/staging/processed/pr_fema_pa_master.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 4 | manual_file_required | fema_pa_hmgp | data/staging/processed/pr_fema_pa_master.csv | Provide validated manual file in dropzone | no_file_present |
| 5 | endpoint_blocked | fema_pa_hmgp | data/staging/processed/pr_fema_hmgp_master.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 5 | manual_file_required | fema_pa_hmgp | data/staging/processed/pr_fema_hmgp_master.csv | Provide validated manual file in dropzone | no_file_present |
| 6 | endpoint_blocked | federal_research | data/staging/processed/pr_research_master.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 6 | manual_file_required | federal_research | data/staging/processed/pr_research_master.csv | Provide validated manual file in dropzone | no_file_present |
| 7 | manual_file_required | sba_loans | data/staging/processed/pr_sba_loans_master.csv | Provide validated manual file in dropzone | no_file_present |
| 9 | endpoint_blocked | hud_cdbg | data/staging/processed/pr_cdbg_dr_master.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 9 | manual_file_required | hud_cdbg | data/staging/processed/pr_cdbg_dr_master.csv | Provide validated manual file in dropzone | no_file_present |
| 14 | manual_file_required | federal_sectoral_sbir | data/staging/processed/pr_sbir_master.csv | Provide validated manual file in dropzone | no_file_present |
| 16 | manual_file_required | federal_sectoral_usace | data/staging/processed/pr_usace_civil_master.csv | Provide validated manual file in dropzone | no_file_present |
| 16 | producer_blocked | federal_sectoral_usace | data/staging/processed/pr_usace_civil_master.csv | Resolve producer failure and retry | 2026-05-08 21:00:18 [INFO] Starting USACE civil works download for Puerto Rico... 2026-05-08 21:00:18 [INFO] [Window 2000f2009] 2007-10-01 to 2009-09-30 2026-05-08 21:00:18 [INFO] Fetching usace_civil_pop_2000f2009.csv (filter=pop) 2026-05-08 21:00:18 [ERROR] HTTP 422 — skipping: {"message":"'award_type_codes' must onl |
| 18 | endpoint_blocked | usaspending_federal_awards_backbone | data/staging/expansion/expansion_idv_indirect_pr.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 18 | manual_file_required | usaspending_federal_awards_backbone | data/staging/expansion/expansion_idv_indirect_pr.csv | Provide validated manual file in dropzone | no_file_present |
| 19 | endpoint_blocked | usaspending_federal_awards_backbone | data/staging/expansion/expansion_dod_upr_2001_2015.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 19 | manual_file_required | usaspending_federal_awards_backbone | data/staging/expansion/expansion_dod_upr_2001_2015.csv | Provide validated manual file in dropzone | no_file_present |
| 20 | endpoint_blocked | usaspending_federal_awards_backbone | data/staging/expansion/expansion_dod_upr_2016_2025.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 20 | manual_file_required | usaspending_federal_awards_backbone | data/staging/expansion/expansion_dod_upr_2016_2025.csv | Provide validated manual file in dropzone | no_file_present |
| 21 | endpoint_blocked | usaspending_federal_awards_backbone | data/staging/expansion/expansion_reconstruction_2017_2025.csv | Resolve endpoint access/availability and retry | command timed out after 20s |
| 21 | manual_file_required | usaspending_federal_awards_backbone | data/staging/expansion/expansion_reconstruction_2017_2025.csv | Provide validated manual file in dropzone | no_file_present |
