# MoneySweep V2 Public-Source Exhaustion v1

## Scope

This document implements the public-source-first continuation required by the binding VECTOR_C specification. It records what has been discovered, what has actually been retrieved or parsed, what remains blocked by artifact access, and which downstream analytical layers must remain closed.

## Current state

`VECTOR_C = BOUNDED_EXHAUSTION_WITH_PUBLIC_ARTIFACT_BLOCKERS`

This is **not** `PUBLIC_SOURCE_EXHAUSTED`, **not** `SOURCE_ABSENT`, and **not** `CERTIFIED`.

The current FY2025 direct-investment-profit denominator remains **41,664.1 million USD**. The sector layer remains **0 classified / 41,664.1 unresolved** because no current authoritative sector allocation has been retrieved and validated.

## Authoritative workbook gate

The Puerto Rico Planning Board currently publishes three mandatory 2025 workbook manifestations:

1. `Tablas de Ingreso y Producto 2025`
2. `Tablas Balanza de Pagos y Posición de Inversión Internacional de Puerto Rico 2025`
3. `Tablas – Apéndice Estadístico 2025`

Exact public XLSX endpoints are frozen in `data/manifests/macro/jp_public_exhaustion_v1.json`.

Fresh acquisition retries still fail because:

- the web retrieval layer resolves the URLs but rejects XLSX MIME content;
- direct container download also fails;
- the shell/Python path cannot resolve `docs.pr.gov` in this environment;
- therefore byte size, SHA256, ZIP-member inventory, formula/cached-value comparison, and hidden/very-hidden worksheet inspection remain blocked.

These are access/tool failures. `UNRETRIEVED != ABSENT` and `TOOL_FAILURE != SOURCE_FAILURE` remain binding.

### Restartable acquisition and audit

MoneySweep now contains:

- `scripts/acquire_jp_macro_workbooks.py`
- `scripts/audit_jp_macro_workbooks.py`
- `tests/test_acquire_jp_macro_workbooks.py`
- `tests/test_audit_jp_macro_workbooks.py`

The acquisition stage generates source URL, resolved URL, response headers, retrieval UTC, raw byte size, SHA256, and a source manifest directly from bytes. It fails closed on non-XLSX/invalid ZIP responses and records failed retrieval as `RETRIEVAL_BLOCKED_NOT_SOURCE_ABSENT`.

The audit stage inventories ZIP members, visible/hidden/veryHidden worksheets, dimensions, merged cells, formula cells and cached-value manifestations, then searches every sheet without assuming row 1 is a header. Semantic hits preserve whole rows.

## Questionnaire universe

The live Planning Board publication pages expose a broad current Ingreso Neto questionnaire universe covering agriculture, mining, utilities, construction, manufacturing, beverage manufacturing, wholesale, retail, gasoline stations, transportation, air transportation, couriers, information, finance/insurance, brokerages, insurance carriers, real estate, management companies, professional/technical services, administrative support, education, health, arts/recreation, accommodation/food, other services, and specialized insurance forms.

The manifest is `data/manifests/macro/jp_questionnaire_universe_v1.json`.

Most direct document links resolve to official `.doc` manifestations but the retrieval layer rejects `application/msword`. One currently listed property/casualty insurance manifestation returned 404 while the title remains listed publicly; this is classified as a broken manifestation candidate, **not** source absence.

A blank questionnaire listing proves collection architecture, not respondent microdata or a published direct-investment-profit allocation.

## Methodology bridge

Planning Board Social Accounts methodology confirms a real sector-statistics production pathway:

- direct-investment-firm profit information is used to prepare base data by industrial sector;
- the direct-investment-firm universe/register is controlled and missing responses are followed or estimated;
- BOP maintains a multi-source direct-investment-profit database drawing on tax-return, questionnaire and Income Net inputs;
- Income Net data are collected at company level and aggregated by NAICS;
- source instruments include `BP-11`, `IP-11`, `IP-546`, `IP-553` and industry-specific questionnaires.

This proves that a sector production mechanism exists. It does **not** supply FY2025 sector amounts.

## Historical sector publication lineage

`data/manifests/macro/jp_di_profit_sector_lineage_v1.json` preserves the bounded publication lineage.

The 1995 Economic Report contains an explicit table titled `GANANCIAS (PERDIDAS) DE LAS INVERSIONES DIRECTAS POR SECTOR`. FY1995 reports total direct-investment profits of 14,329.5 million and manufacturing profits of 13,694.3 million, or 95.6 percent.

Later publications continue the aggregate direct-investment-profit concept, and Planning Board methodology continues the sector production path, but no current FY2025 sector allocation has been recovered from the parsed public report set.

Therefore:

- historical sector table = `HISTORICAL_SUPPORTING_ONLY`;
- historical share must not be carried forward;
- concept continuity is not value continuity.

## BOP/IIP lineage and revision control

The public BOP/IIP lineage from 2018 through 2025 is bounded in `data/manifests/macro/jp_bop_iip_lineage_v1.json`.

The current 2025 publication reports direct-investment-income debit for FY2018–FY2025 as:

`40,186.3 | 39,750.1 | 35,035.1 | 36,063.8 | 37,618.9 | 38,865.2 | 42,332.2 | 43,249.7`

Observed revision genealogy is preserved rather than overwritten. The 2024 publication reported FY2023/FY2024 values of 39,092.0 / 42,530.6 million; the 2025 publication revises them to 38,865.2 / 42,332.2 million. FY2022 remains 37,618.9 million in both observed vintages.

No parsed public BOP PDF in this bounded pass supplied a current industry or counterparty-country allocation that can close the national-accounts `profits of direct investments` denominator.

## National Accounts versus BOP diagnostic bridge

`data/staging/processed/macro/pr_na_bop_di_bridge_v0.csv` preserves the current FY2021–FY2025 comparison:

| FY | National Accounts DI profits | BOP DI-income debit | BOP − NA | Difference / NA |
|---|---:|---:|---:|---:|
| 2021 | 34,174.4 | 36,063.8 | 1,889.4 | 5.529% |
| 2022 | 36,466.2 | 37,618.9 | 1,152.7 | 3.161% |
| 2023 | 37,512.6 | 38,865.2 | 1,352.6 | 3.606% |
| 2024 | 40,857.7 | 42,332.2 | 1,474.5 | 3.609% |
| 2025 | 41,664.1 | 43,249.7 | 1,585.6 | 3.806% |

Every row remains `NONCOMPARABLE_AS_IDENTITY`. The consistent numerical relationship is diagnostic; it is not an authoritative bridge allowing one measurement domain to substitute for the other.

FY2021 also retains the separate stale-macro-revision warning already encoded in the factor-income ledger.

## Binding gates

The following remain mandatory:

- `UNRETRIEVED != ABSENT`
- `TOOL_FAILURE != SOURCE_FAILURE`
- `PUBLIC_SOURCES_BEFORE_PUBLIC_RECORDS_REQUESTS`
- `INDUSTRY_GDP != DIRECT_INVESTMENT_PROFITS`
- `INDUSTRY_NET_INCOME != DIRECT_INVESTMENT_PROFITS`
- `HISTORICAL_SECTOR_SHARE != CURRENT_SECTOR_SHARE`
- `METHODOLOGY_EXISTS != CURRENT_AMOUNT`
- `NATIONAL_ACCOUNTS_DI_PROFITS != BOP_DI_INCOME`
- `AGGREGATE != SECTOR`
- `SECTOR != COMPANY`
- `COMPANY != ULTIMATE_OWNER`
- `ULTIMATE_PARENT_COUNTRY != CASH_DESTINATION`
- `REST_OF_WORLD != UNITED_STATES`
- `UNKNOWN != ZERO`

## Downstream certification state

| Layer | State |
|---|---|
| Macro FY2010–FY2025 denominator | PROVISIONAL CLOSED |
| FY2022–FY2025 profit/dividend identities | PROVISIONAL CLOSED |
| FY2021 factor-account alignment | UNRESOLVED |
| Planning Board sector-production methodology | FACT / FOUND |
| Historical DI-profit sector table | PASS / HISTORICAL SUPPORT ONLY |
| NA↔BOP direct-investment equivalence | FAIL / NONCOMPARABLE AS IDENTITY |
| Current sector DI-profit allocation | BLOCKED |
| Company dollar allocation | BLOCKED_UPSTREAM |
| Ownership dollar allocation | BLOCKED_UPSTREAM |
| Destination-country dollar allocation | BLOCKED_UPSTREAM |
| United States share | UNKNOWN |
| Public-source exhaustion | OPEN |
| Public-records/FOIA escalation | NOT_YET_REACHED |

## Required continuation

1. Acquire and byte-freeze the three 2025 JP XLSX workbooks.
2. Inventory ZIP members and every visible/hidden/veryHidden sheet before semantic parsing.
3. Preserve formulas and cached values separately.
4. Search all sheets for direct-investment/profit/dividend/sector/industry terminology without assuming row 1 is a header.
5. Test only measurement-compatible whole-row sector candidates against 41,664.1 million.
6. Acquire and freeze the current questionnaire documents and instructions; inspect exact collection fields and aggregation definitions.
7. Repeat workbook/schema review through the 2018–2024 BOP/IIP lineage.
8. Continue revision genealogy without replacing older manifestations.
9. Reconcile national-account direct-investment profits to BPM6 direct-investment income only through authoritative methodology.
10. If no current sector denominator emerges after those public artifacts are physically exhausted, freeze sector attribution as `BLOCKED_PUBLIC_SOURCE_EXHAUSTED`.
11. Only then may company/entity evidence begin, and dollar allocation remains independent of ownership identity.
