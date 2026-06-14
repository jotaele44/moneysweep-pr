# Source Materialization Readiness

Total sources: **126**
Automatable: **67** (ready: **67**, need API key at run time: 8)
Queued / excluded: **59**

## Path types

| path_type | automatable | count | recommended_action |
| --- | --- | --- | --- |
| `api_adapter` | True | 42 | Materialize via `python -m contract_sweeper.query --source <id>` (set key if gated). |
| `api_producer` | True | 25 | Run producer under strict preflight; public API path, set key if gated. |
| `manual_export` | False | 36 | Operator delivers file to the dropzone; see manual_export_registry.yaml + runbook. |
| `scraper_needed` | False | 16 | Queued: needs a scraping adapter for the PR-gov HTML/PDF surface. |
| `deferred_stub` | False | 4 | Intentionally unimplemented; remains not_materialized by design. |
| `semantic_duplicate` | False | 3 | No action; covered by sibling source. |

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

## api_producer (25)

- `dol_whd_osha`
- `emma_infra_revenue`
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
- `prasa_contracts_master`
- `sam_exclusions`
- `sec_13f_nport`
- `sec_edgar`
- `sf133_budget_execution`
- `ssa`
- `usace_permits`
- `usaspending_loans`
- `usda_farm_subsidies`

## deferred_stub (4)

- `census_gov_finances`
- `fta_ntd`
- `nara_catalog_aws_open_data`
- `nara_nextgen_catalog_v3`

## manual_export (36)

- `act_toll_revenue`
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
- `dtop_road_contracts`
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
- `ports_airports_contracts`
- `ports_airports_revenue`
- `ports_authority`
- `pr_cabilderos`
- `pr_corporate_registry`
- `prasa`
- `prasa_rate_revenue`
- `prepa_luma_rate_revenue`
- `prpha_housing_subsidy`
- `tourism_room_tax`
- `transit_contracts`
- `transit_fare_revenue`

## scraper_needed (16)

- `aafaf`
- `cofina`
- `compras_pr`
- `cor3`
- `emma_bonds`
- `eqb_epa_icis`
- `hacienda`
- `hacienda_sut_ivu`
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
