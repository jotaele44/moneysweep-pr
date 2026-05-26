# Source Recovery Matrix

Total sources: **82**

## Bucket counts

| failure_bucket | count | recommended_action |
| --- | --- | --- |
| `public_api_adapter_ready` | 26 | Query via `python -m contract_sweeper.query --source <id>`; bulk producer unblocked by validation, not adapter work. |
| `never_run_or_unverified` | 24 | Run producer to determine bucket. |
| `html_pdf_or_pr_gov_custom` | 20 | Defer; needs scraping adapter design pass. |
| `manual_export_only` | 5 | External delivery to `data/manual_import_dropzone/<family>/`; see SOURCE_RECOVERY_RUNBOOK. |
| `auth_or_key_gated` | 3 | Set the required credential env var in `.env`; rerun producer. |
| `semantic_duplicate` | 3 | No action; covered by sibling source. |
| `required_missing_blocker` | 1 | Escalate; required source has no available path. |

## auth_or_key_gated (3)

- `highergov_supplemental`
- `opencorporates`
- `sam_entities`

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

## never_run_or_unverified (24)

- `chip`
- `cms_open_payments`
- `dol_whd_osha`
- `fcc_usf`
- `fhlb`
- `gao_ig_audits`
- `hud_hcv_section8`
- `lihtc`
- `medicaid_fmap`
- `medicare_advantage`
- `medicare_parts`
- `ncua`
- `nmtc`
- `ofac_sdn`
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

## public_api_adapter_ready (26)

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
- `lda`
- `nfip_claims`
- `nih_reporter`
- `nonprofits_irs990`
- `oia_grants`
- `research_grants`
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
