# Financial Data-Source Audit

Registry sources: **123** (financial: **116**, supporting/reference: **7**). Not-yet-considered candidates: **6**.

_Read-only re-projection of `reports/source_recovery_matrix.csv` + live producer health into money-flow audit buckets. Regenerate with `python3 scripts/build_financial_source_audit.py`._

## Status buckets (all sources)

| audit_status | all | financial | meaning |
| --- | --- | --- | --- |
| `wired_materializing` | 2 | 2 | Wired and producing output on disk now. |
| `wired_offline_ready` | 2 | 2 | Wired; materializes fully offline from a committed input (no operator file/network). |
| `wired_ready_unmaterialized` | 58 | 57 | Wired and ready; just needs a run (network egress). |
| `wired_needs_key` | 7 | 3 | Wired and automatable, but its API key is not set. |
| `wired_not_set_to_materialize` | 5 | 3 | Wired but produces nothing by design (deferred stub / sibling duplicate). |
| `queued_manual` | 34 | 34 | Wired, but waits on an operator-delivered manual export. |
| `queued_scraper` | 15 | 15 | Declared, but needs a scraping adapter for a PR-gov HTML/PDF surface. |
| `broken` | 0 | 0 | Producer is missing / fails import / has no callable entrypoint. |
| `not_considered` | 6 | 0 | Real-world financial source with no registry entry yet. |

## The four questions

1. **Which financial sources are wired?** 113 are wired to a producer — 2 producing output now, 2 able to materialize fully offline from committed inputs, 60 automatable & ready to run (incl. key-gated), 49 wired but queued behind a manual export or scraper.
2. **Which don't work?** 0 have a structural producer defect (missing / import error / no entrypoint). Runtime correctness beyond import is not verified offline — see caveat below.
3. **Which aren't set to materialize anything?** 3 produce nothing by design (deferred stubs + semantic duplicates of sibling sources).
4. **Which haven't even been considered?** 6 real-world financial sources have no registry entry (see `financial_source_coverage_gaps.md`).

> **Caveat:** `producer_importable` is a static import/entrypoint check — it does **not** confirm a producer yields valid rows at run time. With outbound egress blocked in this environment, live-API correctness is unverified; only offline-materializable sources are proven end-to-end.

## Financial domains

| financial_domain | sources | materializing | queued |
| --- | --- | --- | --- |
| `debt_and_bonds` | 2 | 0 | 2 |
| `federal_awards` | 62 | 2 | 3 |
| `infrastructure_contracts` | 8 | 0 | 7 |
| `infrastructure_revenue` | 6 | 0 | 5 |
| `lobbying_influence` | 2 | 0 | 1 |
| `manual_financial` | 5 | 0 | 3 |
| `municipal_finance` | 3 | 0 | 3 |
| `nonprofit_funding` | 1 | 0 | 0 |
| `political_finance` | 5 | 0 | 3 |
| `territorial_spending` | 22 | 0 | 22 |

## Producer/source-id name mismatches (23)

Sources whose `source_id` is not recoverable from the producer filename. Legitimate for shared aggregators, but a registry-enumeration risk worth tracking (a rename or audit keyed on filenames can silently miss these).

| source_id | producer | financial_domain |
| --- | --- | --- |
| `acuden_2024_transition` | `ingest_act_transition.py` | manual_financial |
| `contralor_electoral` | `ingest_oce.py` | political_finance |
| `emma_infra_revenue` | `extract_emma_revenue.py` | infrastructure_revenue |
| `federal_audit_clearinghouse` | `download_fac.py` | federal_awards |
| `fema_individual_assistance` | `download_fema_ia.py` | federal_awards |
| `fema_pa_openfema_v2` | `download_openfema_pa_projects.py` | federal_awards |
| `financialdata_net` | `enrich_financialdata_entities.py` | commercial_enrichment |
| `fpds_report_builder` | `download_grants.py` | federal_awards |
| `highergov_supplemental` | `fetch_highergov_api.py` | federal_awards |
| `hud_drgr_authorized` | `ingest_hud_drgr_exports.py` | manual_financial |
| `msrb_rtrs_trades` | `download_msrb_trades.py` | debt_and_bonds |
| `nara_catalog_aws_open_data` | `download_nara_nextgen.py` | archival_provenance |
| `ports_airports_contracts` | `ingest_port_airport_contracts.py` | infrastructure_contracts |
| `ports_airports_revenue` | `ingest_port_airport_revenue.py` | infrastructure_revenue |
| `pr_act_60_decrees` | `download_act60.py` | territorial_spending |
| `pr_corporate_registry` | `ingest_active_contractors.py` | manual_financial |
| `prasa_rate_revenue` | `ingest_utility_revenue.py` | infrastructure_revenue |
| `prepa_luma_genera` | `download_prepa_contracts.py` | infrastructure_contracts |
| `prepa_luma_rate_revenue` | `ingest_utility_revenue.py` | infrastructure_revenue |
| `rum_cover_over` | `download_rum_coverover.py` | territorial_spending |
| `sam_entities` | `sam_enrichment.py` | entity_resolution |
| `sec_13f_nport` | `download_sec_holdings.py` | federal_awards |
| `usaspending_prime` | `build_unified_master.py` | federal_awards |
