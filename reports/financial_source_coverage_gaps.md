# Financial Source Coverage Gaps — "Not Even Considered"

_Deep web-research pass (2026-06-14); reconfirmed 2026-09-12. Enumerates
real-world financial data sources relevant to Puerto Rico public-money
intelligence that have **no entry** in the registry (`registries/source_registry.yaml`,
167 sources effective as of 2026-09-12). Each candidate was checked against
the live registry id list and verified against a primary source._

The machine-readable rows live in `financial_source_coverage_gaps.csv` and are
surfaced in `financial_source_audit.{csv,md}` as the `not_considered` bucket.

**Note on scope (2026-09-12):** this backlog is a distinct gap universe from
`reports/guide_financial_avenue_coverage_v1.md` (the 30-avenue Kevane Grant
Thornton guide projection). That audit's three former route gaps
(GFAV-004/005/020 — OCIF international financial entities, OCS insurance
companies, FTZ Board foreign-trade zones) were closed in a separate pass by
materializing `ocif_guide_financial_classes`, `ocs_insurer_registry`, and
`ftz_board_pr`; none of those three overlap with the real-world revenue/
federal-money gaps tracked below.

**Update (promotions):** six candidates have been **promoted into the registry as
deferred intake stubs** (producer `scripts/download_coverage_gap_intake.py`):
- First P1 batch: `hacienda_sut_ivu` (scraper_needed), `census_gov_finances`,
  `fta_ntd` (deferred_stub).
- P0 own-source-revenue batch (closing the territorial-revenue gap): `pr_act_154_excise`
  and `pr_income_tax_collections` (scraper_needed, Hacienda statistics surface), and
  `pr_general_fund_revenues` (deferred_stub, estadisticas API).

These now appear in the audit ledger as registry sources, not `not_considered`. The
remaining backlog below stays here until a real fetcher/adapter is built — each needs
network egress or an API key, unavailable in the buildout environment.

**Completeness note (PR own-source revenue):** the registry was comprehensive on the
federal-in, influence, debt, and PR-spending axes but had a systematic hole on the
revenue PR raises itself. The P0 promotions addressed the largest pieces (Act 154,
income tax, the consolidated General Fund series).

**Now materialized (automatable):** `pr_general_fund_revenues`,
`pr_income_tax_collections`, and `estadisticas_pr_external_trade` are wired to a real
producer — `scripts/download_estadisticas_pr.py` — which pulls them from the **Datos.PR
CKAN API** (`datos.estadisticas.pr`). All three are `api_producer` (automatable); they
materialize on a networked run (egress-blocked sandbox writes an empty schema gracefully).

**PRASA financial-infrastructure evidence (P0):** `prasa_cer` (CER / audited statements),
`prasa_cip` (capital improvement program), and `prasa_completed_projects` (FEMA 406 /
COR3 recovery bridge) are now registered as `manual_export` sources with a real parser
(`scripts/ingest_prasa_cer.py`), awaiting operator CSV extracts in `data/raw/PRASA/<cer|
cip|completed>/`.

Remaining revenue-side backlog: `pr_arbitrios_excise` (alcohol/tobacco/fuel/cement/sugar/
plastics, Hacienda SC-2225) and `pr_ui_trust_fund` on the labor side.

## Context

The registry is already broad — CRIM property tax, IRS 990, SEC EDGAR, the Federal
Audit Clearinghouse (Single Audit), Opportunity Zones, SLFRF, HAF, and dozens of
federal-agency grant feeds are all present. The genuine gaps are therefore narrow
and specific: a handful of **major revenue streams and federal-money flows** that
no current source captures. They are listed below, highest-leverage first.

## Prioritized backlog

_Reconfirmed absent from the live registry on 2026-09-12 (see command below).
`hacienda_sut_ivu`, `census_gov_finances` and `fta_ntd` are omitted from this
table because they were already promoted — see "Update (promotions)" above._

| # | candidate `source_id` | flow captured | why it's a gap | access | priority |
|---|---|---|---|---|---|
| 1 | `gsa_iolp_real_property` | GSA Inventory of Owned & Leased Properties — federal leases in PR (lease payments to PR landlords) | A **federal-money-into-PR** flow adjacent to procurement that the USAspending contract feed does not surface. Full dataset published on Data.gov; filter `state=PR`. | Data.gov bulk / IOLP | **P1** |
| 2 | `pr_arbitrios_excise` | PR excise/arbitrios on alcohol, cigarettes, fuel/petroleum, cement, sugar, plastics (Form SC-2225 monthly) | Vehicle arbitrios are partially covered via `dtop_vehicle_fees`; the remaining excise streams (largest own-source revenue lane still uncaptured after the P0 Act 154/income-tax/General Fund promotions) are not. | Hacienda SC-2225 monthly arbitrios series (scrape/bulk) | **P1** |
| 3 | `hmda_ffiec` | Home Mortgage Disclosure Act loan-application register — mortgage credit flows in PR | The registry has institution-health sources (`fdic`, `ncua`, `fhlb`) but no **mortgage-origination** flow. Adjacent to the `lihtc` / `nmtc` / `opportunity_zones` housing-finance lens. | FFIEC/CFPB modified-LAR bulk + Data Browser | P2 |
| 4 | `prac_pandemic_oversight` | PRAC consolidated pandemic spending (SLFRF, SVOG, RRF, PPP) + IG findings | **High overlap** with existing `slfrf` / `sba_ppp` / `usaspending`. Worth it only as a curated pandemic-tag crosswalk + oversight-findings layer, not a primary source. | PandemicOversight.gov Data Exports | P2 |
| 5 | `pr_ui_trust_fund` | PR DOL Unemployment Insurance Trust Fund — employer payroll-tax contributions and fund balances | Federal Disaster Unemployment Assistance is already covered via FEMA; the territorial UI trust fund itself (contributions/balances) is not. | US DOL ETA UI financial data (oui.doleta.gov) + PR DOL | P2 |

## Notes on method & confidence

- Each `source_id` above was reconfirmed **absent** from the live registry
  (167 effective sources as of 2026-09-12; no alias or sibling covers the same
  flow) via `grep -c "source_id: <id>$" registries/source_registry.yaml`.
- Items 1 and 3–5 are **API/bulk automatable** — they would land in the
  `automatable` set, not the manual/scraper queue. Item 2 (PR arbitrios/excise)
  is a scraper/bulk surface like the existing Hacienda SC-2225 series.
- Item 4 is deliberately P2: it is mostly a re-cut of data the registry already
  ingests; recommend evaluating it as enrichment rather than a new primary table.
- Lower-confidence candidates not promoted to the table (need more scoping before
  intake): FFIEC bank Call Reports (institution-level, adjacent to `fdic`); FAA
  AIP airport grants (likely already inside `usaspending`).

## Sources

- [Hacienda — IVU/SUT Revenues](https://hacienda.pr.gov/inversionistas/estadisticas-y-recaudos-statistics-and-revenues/ingresos-del-impuesto-sobre-ventas-y-uso-ivu-sales-and-use-tax-sut-revenues)
- [Census — State & Local Government Finances Datasets](https://www.census.gov/programs-surveys/gov-finances/data/datasets.html)
- [Census — Data Developers / APIs](https://www.census.gov/data/developers/data-sets.html)
- [FTA — National Transit Database](https://www.transit.dot.gov/ntd)
- [GSA IOLP on Data.gov](https://catalog.data.gov/dataset/inventory-of-owned-and-leased-properties-iolp)
- [FFIEC/CFPB — HMDA Data Browser](https://ffiec.cfpb.gov/data-browser/)
- [PRAC — Pandemic Oversight Data Downloads](https://www.pandemicoversight.gov/news-and-resources/data)
- [Hacienda — Arbitrios de Vehículos (SC-2225 series)](https://hacienda.pr.gov/arbitrios/arbitrios-en-el-caso-de-vehiculos)
- [US DOL ETA — UI Data Dashboard](https://oui.doleta.gov/unemploy/DataDashboard.asp)
