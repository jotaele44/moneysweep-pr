# Source Materialization Readiness

Total sources: **113**
Automatable: **65** (ready: **65**, need API key at run time: 8)
Queued / excluded: **48**

## Path types

| path_type | automatable | count | recommended_action |
| --- | --- | --- | --- |
| `api_adapter` | True | 42 | Materialize via `python -m contract_sweeper.query --source <id>` (set key if gated). |
| `api_producer` | True | 23 | Run producer under strict preflight; public API path, set key if gated. |
| `manual_export` | False | 28 | Operator delivers file to the dropzone; see manual_export_registry.yaml + runbook. |
| `scraper_needed` | False | 15 | Queued: needs a scraping adapter for the PR-gov HTML/PDF surface. |
| `semantic_duplicate` | False | 3 | No action; covered by sibling source. |
| `deferred_stub` | False | 2 | Intentionally unimplemented; remains not_materialized by design. |

API keys needed for full automatable materialization: `FAC_API_KEY`, `FEC_API_KEY`, `FINANCIALDATA_API_KEY`, `HIGHERGOV_API_KEY`, `OPENCORPORATES_API_TOKEN`, `SAM_API_KEY`

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

## api_producer (23)

- `dol_whd_osha`
- `fcc_usf`
- `fec_committees`
- `federal_audit_clearinghouse`
- `fema_individual_assistance`
- `financialdata_net`
- `gao_ig_audits`
- `hud_cdbg_dr_public`
- `hud_cdbg_mit`
- `lihtc`
- `ncua`
- `ngo_integration_layer`
- `nmtc`
- `opm_fedscope`
- `opportunity_zones`
- `sam_exclusions`
- `sec_13f_nport`
- `sec_edgar`
- `sf133_budget_execution`
- `ssa`
- `usace_permits`
- `usaspending_loans`
- `usda_farm_subsidies`

## deferred_stub (2)

- `nara_catalog_aws_open_data`
- `nara_nextgen_catalog_v3`

## manual_export (28)

- `act_tolls_concession`
- `act_transition_contracts`
- `acuden_2024_transition`
- `ases_plan_vital`
- `bde_loans`
- `contralor_electoral`
- `crim_property_tax`
- `dcaa_active_contractors`
- `ddec_incentives`
- `doj_settlements`
- `donaciones_pr`
- `dtop_vehicle_fees`
- `equitable_sharing`
- `follow_the_money`
- `gaming_commission`
- `hud_drgr_authorized`
- `irs_ctc_eitc_pr`
- `loteria_pr`
- `oatrh_payroll`
- `ocpr_contracts`
- `oficina_contralor`
- `ogpe_permits`
- `ports_authority`
- `pr_cabilderos`
- `pr_corporate_registry`
- `prasa`
- `prpha_housing_subsidy`
- `tourism_room_tax`

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
