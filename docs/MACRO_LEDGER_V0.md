# MoneySweep V2 Macro Ledger v0

## Scope

This vector establishes a bounded Puerto Rico fiscal-year GDP/GNP reconciliation ledger for FY2010-FY2025. It is a macro-accounting layer only. It does not attribute any aggregate to a company, owner, jurisdiction, tax policy, lobbyist, campaign contribution, or misconduct claim.

## Governing identity

`GDP - GNP` is stored as a computed accounting differential. It is not labeled capital flight, leakage, transfer to the United States, or corporate extraction.

The source-reported `Less: Rest of the world` amount is preserved separately from the computed differential. Small differences caused by independently rounded one-decimal published figures are classified as `WITHIN_DECLARED_ROUNDING_BUDGET`, never silently rewritten.

## Source manifestations

### JP_AE2019

Puerto Rico Planning Board, *Apendice Estadistico del Informe Economico a la Gobernadora 2019*, Table 9. It provides FY2010-FY2019 gross product, rest-of-world adjustment, and GDP values. FY2016-FY2019 rows remain in the ledger as historical/superseded manifestations because later Planning Board values exist.

### JP_IP2025

Puerto Rico Planning Board, *Ingreso y Producto 2025 / Income and Product 2025*. The ledger uses Table 9 as the primary current observation surface and preserves the conflicting Table 1 and Table 10 FY2021 observations.

## FY2021 contradiction

The 2025 publication contains two incompatible FY2021 macro value pairs:

- Table 1 / Table 9 manifestation: GNP 73,357.2; GDP 106,426.6; computed GDP-GNP 33,069.4 million.
- Table 10 manifestation: GNP 72,950.6; GDP 106,368.9; computed GDP-GNP 33,418.3 million.

Both appear under the same Planning Board publication vintage. Count equality, majority-of-tables, deterministic ordering, or nearest arithmetic fit are not sufficient adjudication evidence. FY2021 therefore remains `UNRESOLVED` and blocks any certified continuous FY2010-FY2025 canonical series.

## Revision handling

Earlier observations are never deleted. Later authoritative manifestations may displace an older value only at the canonical-view layer. Displaced rows remain `SUPERSEDED` with an explicit successor observation identifier.

Current bounded state:

- fiscal-year denominator: 16 years (FY2010-FY2025)
- observation rows: 22
- historical superseded rows: 4
- unresolved fiscal years: 1 (FY2021)
- source bytes frozen: no
- macro ledger certification: `PROVISIONAL`
- entity attribution: `BLOCKED_UNTIL_MACRO_CLOSURE`

## Required next gates

1. Acquire and freeze the exact authoritative source bytes.
2. Record byte size and SHA-256 for each manifestation.
3. Determine the Planning Board revision lineage controlling FY2021; do not resolve by table count.
4. Re-run row-count, stable-ID, fiscal-year coverage, revision, and arithmetic-closure tests.
5. Materialize one canonical annual view only when every fiscal year has a unique latest authoritative value pair.
6. Only then begin factor-income decomposition, sector allocation, entity binding, owner-jurisdiction attribution, and retention metrics.

## Interpretation safeguards

- `Rest of world` is not synonymous with United States.
- Macro aggregate is not company-specific flow.
- Sector aggregate is not company-specific flow.
- Facility location is not economic ownership.
- Corporate parent is not beneficial owner unless independently bound.
- Tax expenditure is not demonstrated net economic loss.
- Lobbying is not influence.
- Campaign contribution is not quid pro quo.
- UNKNOWN is not zero.
