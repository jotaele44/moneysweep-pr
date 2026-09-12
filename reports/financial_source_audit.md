# Financial Data-Source Audit

Registry sources: **167** (financial: **158**, supporting/reference: **9**). Not-yet-considered candidates: **5**.

_Read-only re-projection of `reports/source_recovery_matrix.csv` + live producer health into money-flow audit buckets. Regenerate with `python3 scripts/build_financial_source_audit.py`._

## Status buckets (all sources)

| audit_status | all | financial | meaning |
| --- | --- | --- | --- |
| `wired_materializing` | 16 | 15 | Wired and producing output on disk now. |
| `wired_offline_ready` | 3 | 3 | Wired; materializes fully offline from a committed input (no operator file/network). |
| `wired_ready_unmaterialized` | 92 | 88 | Wired and ready; just needs a run (network egress). |
| `wired_needs_key` | 10 | 8 | Wired and automatable, but requires an API key (gated by the registry auth). |
| `wired_not_set_to_materialize` | 5 | 3 | Wired but produces nothing by design (deferred stub / sibling duplicate). |
| `queued_manual` | 39 | 39 | Wired, but waits on an operator-delivered manual export. |
| `queued_scraper` | 2 | 2 | Declared, but needs a scraping adapter for a PR-gov HTML/PDF surface. |
| `broken` | 0 | 0 | Producer is missing / fails import / has no callable entrypoint. |
| `not_considered` | 5 | 0 | Real-world financial source with no registry entry yet. |

## The four questions

1. **Which financial sources are wired?** 155 are wired to a producer — 15 producing output now, 3 able to materialize fully offline from committed inputs, 96 automatable & ready to run (incl. key-gated), 41 wired but queued behind a manual export or scraper.
2. **Which don't work?** 0 have a structural producer defect (missing / import error / no entrypoint). Runtime correctness beyond import is not verified offline — see caveat below.
3. **Which aren't set to materialize anything?** 3 produce nothing by design (deferred stubs + semantic duplicates of sibling sources).
4. **Which haven't even been considered?** 5 real-world financial sources have no registry entry (see `financial_source_coverage_gaps.md`).

> **Caveat:** `producer_importable` is a static import/entrypoint check — it does **not** confirm a producer yields valid rows at run time. With outbound egress blocked in this environment, live-API correctness is unverified; only offline-materializable sources are proven end-to-end.

## Financial domains

| financial_domain | sources | materializing | queued |
| --- | --- | --- | --- |
| `debt_and_bonds` | 2 | 1 | 0 |
| `federal_awards` | 65 | 5 | 3 |
| `infrastructure_contracts` | 20 | 1 | 13 |
| `infrastructure_revenue` | 6 | 0 | 5 |
| `lobbying_influence` | 2 | 1 | 1 |
| `manual_financial` | 6 | 0 | 4 |
| `municipal_finance` | 3 | 0 | 2 |
| `nonprofit_funding` | 1 | 0 | 0 |
| `political_finance` | 8 | 2 | 2 |
| `territorial_spending` | 30 | 2 | 11 |
| `uncategorized` | 15 | 3 | 0 |

## Producer/source-id name mismatches (44)

Sources whose `source_id` is not recoverable from the producer filename. Legitimate for shared aggregators, but a registry-enumeration risk worth tracking (a rename or audit keyed on filenames can silently miss these).

| source_id | producer | financial_domain |
| --- | --- | --- |
| `acuden_2024_transition` | `ingest_act_transition.py` | manual_financial |
| `campaign_finance_materialization_gate` | `validate_campaign_finance_materialization.py` | political_finance |
| `centinelas_pre_official_signals` | `ingest_centinelas_signals.py` | uncategorized |
| `contralor_electoral` | `ingest_oce.py` | political_finance |
| `emma_infra_revenue` | `extract_emma_revenue.py` | infrastructure_revenue |
| `eqb_epa_icis` | `download_epa_echo_icis.py` | territorial_spending |
| `federal_audit_clearinghouse` | `download_fac.py` | federal_awards |
| `fema_individual_assistance` | `download_fema_ia.py` | federal_awards |
| `fema_pa_openfema_v2` | `download_openfema_pa_projects.py` | federal_awards |
| `financialdata_net` | `enrich_financialdata_entities.py` | commercial_enrichment |
| `fpds_report_builder` | `download_grants.py` | federal_awards |
| `hacienda_sut_ivu` | `download_coverage_gap_intake.py` | territorial_spending |
| `highergov_supplemental` | `fetch_highergov_api.py` | federal_awards |
| `hud_drgr_authorized` | `ingest_hud_drgr_exports.py` | manual_financial |
| `legislapr_discovery` | `probe_legislapr_detail.py` | uncategorized |
| `legislative_fiscal_link_candidates` | `build_legislative_links.py` | uncategorized |
| `msrb_rtrs_trades` | `download_msrb_trades.py` | debt_and_bonds |
| `municipal_finance` | `download_fac_municipal.py` | municipal_finance |
| `nara_catalog_aws_open_data` | `download_nara_nextgen.py` | archival_provenance |
| `ocs_insurer_registry` | `scrape_ocs_insurers.py` | uncategorized |
| `oficina_contralor` | `scrape_iapconsulta.py` | territorial_spending |
| `ports_airports_contracts` | `ingest_port_airport_contracts.py` | infrastructure_contracts |
| `ports_airports_revenue` | `ingest_port_airport_revenue.py` | infrastructure_revenue |
| `pr_act_154_excise` | `download_coverage_gap_intake.py` | territorial_spending |
| `pr_act_60_decrees` | `download_act60.py` | territorial_spending |
| `pr_corporate_registry` | `ingest_active_contractors.py` | manual_financial |
| `pr_general_fund_revenues` | `download_estadisticas_pr.py` | territorial_spending |
| `pr_income_tax_collections` | `download_estadisticas_pr.py` | territorial_spending |
| `prasa_cip` | `ingest_prasa_cer.py` | infrastructure_contracts |
| `prasa_completed_projects` | `ingest_prasa_cer.py` | infrastructure_contracts |
| `prasa_completed_projects_ppp` | `parse_aaa_ports_pdf.py` | infrastructure_contracts |
| `prasa_consulting_engineer_ppp` | `parse_aaa_ports_pdf.py` | infrastructure_contracts |
| `prasa_rate_revenue` | `ingest_utility_revenue.py` | infrastructure_revenue |
| `prepa_luma_genera` | `download_prepa_contracts.py` | infrastructure_contracts |
| `prepa_luma_rate_revenue` | `ingest_utility_revenue.py` | infrastructure_revenue |
| `rdc_demandas_civiles` | `scrape_rdc_demandas.py` | territorial_spending |
| `rum_cover_over` | `download_rum_coverover.py` | territorial_spending |
| `sam_entities` | `run_sam_pipeline.py` | entity_resolution |
| `sba_disaster_loans_pr` | `import_sba_disaster_loans.py` | manual_financial |
| `sec_13f_bpop_8q_certification` | `certify_bpop_sec13f_8q.py` | uncategorized |
| `sec_13f_bpop_golden_freeze` | `acquire_sec13f_bpop_golden.py` | uncategorized |
| `sec_13f_nport` | `download_sec_holdings.py` | federal_awards |
| `sec_equity_identity_v2` | `download_sec_equity_v2.py` | uncategorized |
| `usaspending_prime` | `build_unified_master.py` | federal_awards |
