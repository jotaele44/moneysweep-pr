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

The endpoints are discoverable, but this execution environment cannot yet freeze their bytes:

- the web retrieval layer resolves the URLs but rejects XLSX MIME content;
- the container retrieval path failed DNS/download access to `docs.pr.gov`;
- therefore byte size, SHA256, ZIP-member inventory, formula/cached-value comparison, and hidden/very-hidden worksheet inspection remain blocked.

Tool access failure is not source absence.

## Questionnaire universe

The live Planning Board publication pages expose a broad current Ingreso Neto questionnaire universe covering agriculture, mining, utilities, construction, manufacturing, beverage manufacturing, wholesale, retail, gasoline stations, transportation, air transportation, couriers, information, finance/insurance, brokerages, insurance carriers, real estate, management companies, professional/technical services, administrative support, education, health, arts/recreation, accommodation/food, other services, and specialized insurance forms.

The manifest is `data/manifests/macro/jp_questionnaire_universe_v1.json`.

Most direct document links resolve to official `.doc` manifestations but the web retrieval layer rejects `application/msword`. One currently listed property/casualty insurance manifestation returned 404 while the title remains listed publicly; this is classified as a broken manifestation candidate, **not** source absence.

A blank questionnaire listing proves collection architecture, not respondent microdata or a published direct-investment-profit allocation.

## BOP/IIP lineage

The public BOP/IIP lineage from 2018 through 2025 has been bounded in `data/manifests/macro/jp_bop_iip_lineage_v1.json`.

Parsed public PDFs confirm that direct-investment income/financial-account measures are present in the modern BPM6-era series. No parsed public PDF in this bounded pass supplied a current industry or country allocation that can close the national-accounts `profits of direct investments` denominator.

The BOP measure remains non-equivalent to the national-account measure. For FY2025:

- national accounts direct-investment profits: `41,664.1`
- BOP direct-investment income debit: `43,249.7`
- difference: `1,585.6`

This is a diagnostic cross-account relationship, not an identity.

## Binding gates

The following remain mandatory:

- `UNRETRIEVED != ABSENT`
- `TOOL_FAILURE != SOURCE_FAILURE`
- `PUBLIC_SOURCES_BEFORE_PUBLIC_RECORDS_REQUESTS`
- `INDUSTRY_GDP != DIRECT_INVESTMENT_PROFITS`
- `INDUSTRY_NET_INCOME != DIRECT_INVESTMENT_PROFITS`
- `HISTORICAL_SECTOR_SHARE != CURRENT_SECTOR_SHARE`
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
8. Reconcile national-account direct-investment profits to BPM6 direct-investment income only through authoritative methodology.
9. If no current sector denominator emerges after those public artifacts are physically exhausted, freeze sector attribution as `BLOCKED_PUBLIC_SOURCE_EXHAUSTED`.
10. Only then may company/entity evidence begin, and dollar allocation remains independent of ownership identity.
