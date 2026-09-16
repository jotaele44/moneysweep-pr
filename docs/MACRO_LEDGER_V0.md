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

Puerto Rico Planning Board, *Ingreso y Producto 2025 / Income and Product 2025*. Table 9 is the primary current observation surface. Table 1 provides a corroborating FY2021 manifestation, while Table 10 retains an older FY2021 revision that is preserved as a superseded observation rather than deleted.

## FY2021 revision adjudication

The 2025 publication contains two FY2021 macro value pairs:

- later revised pair, carried by Table 1 / Table 9: GNP 73,357.2; GDP 106,426.6; computed GDP-GNP 33,069.4 million;
- older pair, carried by Table 10: GNP 72,950.6; GDP 106,368.9; computed GDP-GNP 33,418.3 million.

This is not resolved by table count, deterministic ordering, or arithmetic proximity. The adjudication uses authoritative temporal revision lineage:

1. the Planning Board's 2022 economic report carries the older FY2021 GDP 106,368.9;
2. the 2023 economic report carries revised FY2021 GDP 106,426.6;
3. the 2024 Statistical Appendix carries FY2021 GNP 73,357.2 and GDP 106,426.6;
4. the 2025 summary and major-industry tables continue the later revised pair.

Accordingly, the older Table 10 pair is classified `SUPERSEDED` with contradiction class `TIME`, and the later pair is the `PROVISIONAL` current candidate. The displaced observation remains in the ledger. This establishes value succession only; it does not prove byte identity between source manifestations.

## Revision handling

Earlier observations are never deleted. Later authoritative manifestations may displace an older value only after authoritative revision evidence supports the succession. Displaced rows remain `SUPERSEDED` with an explicit successor observation identifier.

Current bounded state:

- fiscal-year denominator: 16 years (FY2010-FY2025)
- observation rows: 22
- superseded rows: 5
- unresolved fiscal years at the value-selection layer: 0
- source bytes frozen: no
- macro ledger certification: `PROVISIONAL`
- factor-income decomposition: `OPEN`
- country destination: `OPEN`
- entity attribution: `BLOCKED_UNTIL_MACRO_SOURCE_FREEZE_AND_GATES`

## Certification blocker

The annual value-selection layer is provisionally closed, but the macro ledger is not certified. Exact source bytes have not yet been frozen and SHA-256 hashes are null. In addition, the repository's pull-request CI jobs are currently being created but returning failure without reported execution steps, so CI cannot presently certify this vector.

## Required next gates

1. Acquire and freeze the exact authoritative source bytes.
2. Record byte size and SHA-256 for each source manifestation.
3. Preserve the FY2021 revision evidence and superseded stale observation.
4. Re-run row-count, stable-ID, fiscal-year coverage, revision, and arithmetic-closure tests when CI execution is available.
5. Materialize one canonical annual view from the provisionally closed value series.
6. Decompose factor income before any sector or entity attribution.
7. Bind sectors to entities only where source evidence permits; never allocate residual aggregates to companies by assumption.
8. Compute owner-jurisdiction and retention metrics only after destination arithmetic closes.

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
