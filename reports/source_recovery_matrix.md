# Source Materialization Readiness

Total sources: **85**
Automatable: **55** (ready: **55**, need API key at run time: 5)
Queued / excluded: **30**

## Path types

| path_type | automatable | count | recommended_action |
| --- | --- | --- | --- |
| `api_adapter` | True | 42 | Materialize via `python -m contract_sweeper.query --source <id>` (set key if gated). |
| `api_producer` | True | 13 | Run producer under strict preflight; public API path, set key if gated. |
| `scraper_needed` | False | 15 | Queued: needs a scraping adapter for the PR-gov HTML/PDF surface. |
| `manual_export` | False | 10 | Operator delivers file to the dropzone; see manual_export_registry.yaml + runbook. |
| `semantic_duplicate` | False | 3 | No action; covered by sibling source. |
| `deferred_stub` | False | 2 | Intentionally unimplemented; remains not_materialized by design. |

API keys needed for full automatable materialization: `FEC_API_KEY`, `FINANCIALDATA_API_KEY`, `HIGHERGOV_API_KEY`, `OPENCORPORATES_API_TOKEN`, `SAM_API_KEY`

## api_adapter (42)

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
- `fhlb`
- `grants_gov`
- `haf`
- `hhs_grants`
- `highergov_supplemental`
- `hud_hcv_section8`
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
- `snap_nap`
- `usace_civil_works`
- `usaspending_prime`
- `usaspending_subawards`
- `usda_grants`
- `va_benefits`
- `wic`
- `wioa`

## api_producer (13)

- `dol_whd_osha`
- `fcc_usf`
- `financialdata_net`
- `gao_ig_audits`
- `hud_cdbg_dr_public`
- `lihtc`
- `ncua`
- `nmtc`
- `sec_13f_nport`
- `sec_edgar`
- `sf133_budget_execution`
- `ssa`
- `usace_permits`

## deferred_stub (2)

- `nara_catalog_aws_open_data`
- `nara_nextgen_catalog_v3`

## manual_export (10)

- `act_transition_contracts`
- `acuden_2024_transition`
- `dcaa_active_contractors`
- `donaciones_pr`
- `follow_the_money`
- `hud_drgr_authorized`
- `oficina_contralor`
- `pr_cabilderos`
- `pr_corporate_registry`
- `prasa`

## scraper_needed (15)

- `aafaf`
- `cofina`
- `compras_pr`
- `cor3`
- `emma_bonds`
- `eqb_epa_icis`
- `hacienda`
- `msrb_rtrs_trades`
- `municipal_finance`
- `p3_authority`
- `pr_act_60_decrees`
- `pr_pensions`
- `prepa_luma_genera`
- `promesa_creditors`
- `rum_cover_over`

## semantic_duplicate (3)

- `congressional_earmarks`
- `fpds_report_builder`
- `fsrs_subawards`
