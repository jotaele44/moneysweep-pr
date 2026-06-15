# Financial Source Coverage Gaps — "Not Even Considered"

_Deep web-research pass (2026-06-14). Enumerates real-world financial data sources
relevant to Puerto Rico public-money intelligence that have **no entry** in the
123-source registry (`registries/source_registry.yaml`). Each candidate was
checked against the live registry id list and verified against a primary source._

The machine-readable rows live in `financial_source_coverage_gaps.csv` and are
surfaced in `financial_source_audit.{csv,md}` as the `not_considered` bucket.

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

**Now materialized (automatable):** `pr_general_fund_revenues` and
`pr_income_tax_collections` are wired to a real producer —
`scripts/download_estadisticas_pr.py` — which pulls them from the **Datos.PR CKAN API**
(`datos.estadisticas.pr`). Both are now `api_producer` (automatable) rather than
deferred/scraper; they materialize on a networked run (egress-blocked sandbox writes an
empty schema gracefully). Remaining revenue-side backlog: `pr_arbitrios_excise`
(alcohol/tobacco/fuel/cement/sugar/plastics, Hacienda SC-2225), the
`estadisticas_pr_external_trade` series (the untapped imports/exports part of the same
portal — extend the estadisticas producer), and `pr_ui_trust_fund` on the labor side.

## Context

The registry is already broad — CRIM property tax, IRS 990, SEC EDGAR, the Federal
Audit Clearinghouse (Single Audit), Opportunity Zones, SLFRF, HAF, and dozens of
federal-agency grant feeds are all present. The genuine gaps are therefore narrow
and specific: a handful of **major revenue streams and federal-money flows** that
no current source captures. They are listed below, highest-leverage first.

## Prioritized backlog

| # | candidate `source_id` | flow captured | why it's a gap | access | priority |
|---|---|---|---|---|---|
| 1 | `hacienda_sut_ivu` | PR Sales & Use Tax (IVU/SUT) collections by FY / month / NAICS, + COFIM 1% municipal IVU | The single largest PR consumption-tax revenue stream. The registry's `hacienda` entry is a generic scraper stub; SUT/IVU is published as its own statistical series and is not otherwise captured. | bulk tables on `hacienda.pr.gov` (scrape/download) | **P1** |
| 2 | `census_gov_finances` | Census Annual Survey of State & Local Government Finances + State Government Tax Collections + Public Pensions, for PR (FIPS 72) | No authoritative **aggregate** revenue/expenditure baseline exists in the registry. This is the standard cross-check against `aafaf` (cash flow) and `hacienda` (revenue). API-automatable. | Census Data API (key) / bulk datasets | **P1** |
| 3 | `fta_ntd` | FTA National Transit Database — financial, funding-source, and operating-expense data for PR transit agencies (PRHTA, PRITA, Ports Authority) | The registry's `transit_contracts` / `transit_fare_revenue` are PR-portal sources; NTD adds the **federal funding** and audited operating finance for the same agencies. Free, automatable. | `transit.dot.gov/ntd` annual data products | **P1** |
| 4 | `gsa_iolp_real_property` | GSA Inventory of Owned & Leased Properties — federal leases in PR (lease payments to PR landlords) | A **federal-money-into-PR** flow adjacent to procurement that the USAspending contract feed does not surface. Full dataset published on Data.gov; filter `state=PR`. | Data.gov bulk / IOLP | **P1** |
| 5 | `hmda_ffiec` | Home Mortgage Disclosure Act loan-application register — mortgage credit flows in PR | The registry has institution-health sources (`fdic`, `ncua`, `fhlb`) but no **mortgage-origination** flow. Adjacent to the `lihtc` / `nmtc` / `opportunity_zones` housing-finance lens. | FFIEC/CFPB modified-LAR bulk + Data Browser | P2 |
| 6 | `prac_pandemic_oversight` | PRAC consolidated pandemic spending (SLFRF, SVOG, RRF, PPP) + IG findings | **High overlap** with existing `slfrf` / `sba_ppp` / `usaspending`. Worth it only as a curated pandemic-tag crosswalk + oversight-findings layer, not a primary source. | PandemicOversight.gov Data Exports | P2 |

## Notes on method & confidence

- Each `source_id` above was confirmed **absent** from the 123 live registry ids
  (no alias or sibling covers the same flow).
- P1 items 2–4 and item 5 are **API/bulk automatable** — they would land in the
  `automatable` set, not the manual/scraper queue. Item 1 (Hacienda SUT/IVU) is a
  scraper/bulk surface like the existing `hacienda` entry.
- Item 6 is deliberately P2: it is mostly a re-cut of data the registry already
  ingests; recommend evaluating it as enrichment rather than a new primary table.
- Lower-confidence candidates not promoted to the table (need more scoping before
  intake): PR Departamento del Trabajo unemployment trust-fund flows; FFIEC bank
  Call Reports (institution-level, adjacent to `fdic`); FAA AIP airport grants
  (likely already inside `usaspending`).

## Sources

- [Hacienda — IVU/SUT Revenues](https://hacienda.pr.gov/inversionistas/estadisticas-y-recaudos-statistics-and-revenues/ingresos-del-impuesto-sobre-ventas-y-uso-ivu-sales-and-use-tax-sut-revenues)
- [Census — State & Local Government Finances Datasets](https://www.census.gov/programs-surveys/gov-finances/data/datasets.html)
- [Census — Data Developers / APIs](https://www.census.gov/data/developers/data-sets.html)
- [FTA — National Transit Database](https://www.transit.dot.gov/ntd)
- [GSA IOLP on Data.gov](https://catalog.data.gov/dataset/inventory-of-owned-and-leased-properties-iolp)
- [FFIEC/CFPB — HMDA Data Browser](https://ffiec.cfpb.gov/data-browser/)
- [PRAC — Pandemic Oversight Data Downloads](https://www.pandemicoversight.gov/news-and-resources/data)
