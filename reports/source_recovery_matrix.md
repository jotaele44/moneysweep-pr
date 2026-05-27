# Source Recovery Matrix

Total sources: **82**

## Bucket counts

| failure_bucket | count | recommended_action |
| --- | --- | --- |
| `public_api_adapter_ready` | 35 | Query via `python -m contract_sweeper.query --source <id>`; bulk producer unblocked by validation, not adapter work. |
| `html_pdf_or_pr_gov_custom` | 20 | Defer; needs scraping adapter design pass. |
| `never_run_or_unverified` | 18 | Run producer to determine bucket. |
| `manual_export_only` | 5 | External delivery to `data/manual_import_dropzone/<family>/`; see SOURCE_RECOVERY_RUNBOOK. |
| `semantic_duplicate` | 3 | No action; covered by sibling source. |
| `required_missing_blocker` | 1 | Escalate; required source has no available path. |

## html_pdf_or_pr_gov_custom (20)

- `aafaf`
- `cofina`
- `compras_pr`
- `cor3`
- `donaciones_pr`
- `emma_bonds`
- `eqb_epa_icis`
- `follow_the_money`
- `hacienda`
- `msrb_rtrs_trades`
- `municipal_finance`
- `oficina_contralor`
- `p3_authority`
- `pr_act_60_decrees`
- `pr_cabilderos`
- `pr_pensions`
- `prasa`
- `prepa_luma_genera`
- `promesa_creditors`
- `rum_cover_over`

## manual_export_only (5)

- `act_transition_contracts`
- `acuden_2024_transition`
- `dcaa_active_contractors`
- `hud_drgr_authorized`
- `pr_corporate_registry`

## never_run_or_unverified (18)

- `dol_whd_osha`
- `fcc_usf`
- `fhlb`
- `gao_ig_audits`
- `hud_hcv_section8`
- `lihtc`
- `ncua`
- `nmtc`
- `sec_13f_nport`
- `sec_edgar`
- `sf133_budget_execution`
- `snap_nap`
- `ssa`
- `usace_civil_works`
- `usace_permits`
- `va_benefits`
- `wic`
- `wioa`

## public_api_adapter_ready (35)

- `chip`
- `cms_open_payments`
- `doe_grants`
- `doj_grants`
- `dot_grants`
- `ed_grants`
- `epa_grants`
- `exim_bank`
- `fdic`
- `fec`
- `fema_hmgp`
- `fema_pa_openfema_v2`
- `grants_gov`
- `haf`
- `hhs_grants`
- `highergov_supplemental`
- `lda`
- `medicaid_fmap`
- `medicare_advantage`
- `medicare_parts`
- `nfip_claims`
- `nih_reporter`
- `nonprofits_irs990`
- `ofac_sdn`
- `oia_grants`
- `opencorporates`
- `research_grants`
- `sam_entities`
- `sba_loans`
- `sba_ppp`
- `sbir`
- `slfrf`
- `usaspending_prime`
- `usaspending_subawards`
- `usda_grants`

## required_missing_blocker (1)

- `hud_cdbg_dr_public`

## semantic_duplicate (3)

- `congressional_earmarks`
- `fpds_report_builder`
- `fsrs_subawards`
