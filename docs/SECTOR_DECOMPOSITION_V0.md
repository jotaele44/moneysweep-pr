# MoneySweep V2 Sector Decomposition v0

## Scope

This vector tests whether the current public authoritative Puerto Rico macroeconomic sources support a sector-level decomposition of the aggregate direct-investment-profit outflow already preserved in the MoneySweep macro/factor ledgers.

It does **not** infer sector shares from industrial GDP, gross product, net income, employment, exports, payroll, facility counts, tax incentives, or historical sector proportions.

## Current authoritative denominator

For FY2025 the Planning Board national-account publication reports, in millions of dollars:

- GDP - GNP differential: 41,797.3
- Net profit received from rest of world: -41,560.4
- Profits and dividends paid to rest of world: 42,660.6
- Dividends paid to nonresidents: 996.5
- Direct-investment profits: 41,664.1

These are aggregate accounting observations. They do not identify a current industry allocation.

## Public-source audit

### Current Planning Board Income and Product 2025

The publication exposes detailed industrial series for gross product / GDP (Table 10), private/public net income (Table 12), and functional distribution of net income by industry (Table 13). These industrial series are valid sector-context measures but are not documented as a decomposition of `direct-investment profits`.

Accordingly, MoneySweep must not allocate the FY2025 41,664.1 direct-investment-profit aggregate by applying industry GDP shares, industry net-income shares, payroll shares, facility counts, exports, or any other proxy.

### Current Balance of Payments and International Investment Position 2025

The current balance-of-payments publication reports direct-investment income at the aggregate debit/credit level. The publicly indexed current material reviewed in this vector does not provide a current sector table that closes to the FY2025 direct-investment-profit aggregate used by the national accounts.

The balance-of-payments `direct investment income: debit` measure is also not automatically identical to the national-accounts `profits of direct investments` measure; source taxonomy and accounting concept must remain separate unless the Planning Board supplies an authoritative reconciliation.

### Historical Planning Board evidence

Historical Planning Board economic reports did publish tables explicitly titled `GANANCIAS (PERDIDAS) DE LAS INVERSIONES DIRECTAS POR SECTOR` / direct-investment profits by sector. This proves the sector concept historically existed in the statistical system, but it does **not** authorize extrapolating those historical sector proportions into FY2022-FY2025.

Historical sector distributions therefore remain `HISTORICAL_SUPPORTING` only.

## Certification state

`CURRENT_DIRECT_INVESTMENT_PROFIT_SECTOR_DECOMPOSITION = BLOCKED_PUBLIC_SOURCE_DENOMINATOR`

Reason:

1. aggregate FY2022-FY2025 direct-investment-profit totals are available;
2. current detailed industrial GDP/net-income measures are available;
3. no current public authoritative sector allocation of direct-investment profits was located in the bounded public-source audit;
4. proxy allocation would synthesize sector records not reported by the source.

## Permitted current sector layer

MoneySweep may ingest current industry GDP, gross product, net income, compensation, proprietors' income, exports, employment, and similar values as **sector context** with their own measurement types.

They may be used to answer questions such as:

- Which industries generate the most GDP?
- Which industries have the largest net income or compensation?
- How do industrial structures change over time?

They may **not** answer:

- Which industries received or paid the 41,664.1 million in direct-investment profits?
- What share of the GDP-GNP gap belongs to pharmaceuticals, chemicals, medical devices, manufacturing, finance, or any other sector?

unless an independent authoritative binding source provides that allocation.

## Hard invariants

- Sector GDP != direct-investment profits.
- Sector net income != direct-investment profits.
- Historical sector share != current sector share.
- Manufacturing GDP != manufacturing nonresident-profit outflow.
- Pharmaceutical GDP != pharmaceutical nonresident-profit outflow.
- Industry presence != ownership destination.
- Aggregate != sector.
- Sector != company.
- UNKNOWN != zero.
- Discovery absence is not universal source absence; this claim is bounded to the public sources audited in this vector.

## Next admissible paths

1. Continue public-source discovery for a current Planning Board sector-profit table, downloadable spreadsheet, methodological annex, or data-center export.
2. Freeze and inspect the 2025 Excel tables and balance-of-payments workbook if their downloadable files expose additional columns not represented in the PDF/index.
3. Search successor/historical statistical series for a current continuation of the old direct-investment-profit-by-sector table.
4. If public sources are exhausted and the denominator remains unavailable, keep sector attribution `BLOCKED`; do not substitute an allocation model as canonical fact.

## Current public discovery result

The Planning Board currently exposes downloadable `Tablas de Ingreso y Producto 2025`, a 2025 Statistical Appendix in Excel, Balance of Payments 2025 tables, and a macroeconomic data center. These are therefore the next authoritative public manifestations to exhaust before any request-based vector is considered. Public-source exhaustion is **not yet claimed**.
