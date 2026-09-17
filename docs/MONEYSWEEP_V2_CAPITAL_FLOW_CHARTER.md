# MoneySweep V2 — Puerto Rico Capital-Flow Observatory

**Status:** BINDING architectural charter for V2 implementation  
**Scope:** additive rescope; existing source families, datasets, certifications, and federation boundaries remain preserved unless separately superseded with evidence.

## Mission

MoneySweep is Puerto Rico's evidence-driven capital-flow and public-finance observatory. It reconstructs economic flows across government, corporations, ownership networks, tax incentives, federal transfers, debt, contracts, lobbying, property, recovery assistance, and related financial systems in order to measure where economic value generated in Puerto Rico originates, where it moves, who ultimately receives it, and how much is retained within the Puerto Rican economy.

The primary macroeconomic reconciliation target is the Puerto Rico **GDP−GNP differential**. It is an accounting denominator to explain, not a predetermined misconduct or "leakage" conclusion.

## Governing analytical layers

MoneySweep V2 organizes existing and future evidence through six layers:

1. `MACRO` — GDP, GNP, income accounts, factor-income flows, tax revenue, transfer aggregates.
2. `SECTOR` — industry-level production, compensation, profits, investment, and tax expenditure.
3. `ENTITY` — legal persons, public bodies, facilities, vendors, issuers, funds, and other economic actors.
4. `TRANSACTION` — bounded monetary observations with source, destination, amount, period, and direction.
5. `OWNERSHIP` — immediate parent, ultimate parent, beneficial owner, investor/fund/custodian/control distinctions supplied by the existing capital-and-control subsystem.
6. `POLICY` — tax rules, incentives, legislation, lobbying, campaign finance, fiscal-control actions, and other policy observations.

Policy interpretation is downstream of economic-flow and identity closure.

## Non-negotiable invariants

- Rescope MoneySweep; do not narrow it to a single $41B claim.
- GDP−GNP is the primary reconciliation target, not a predetermined misconduct finding.
- Preserve `INTO_PR`, `WITHIN_PR`, `OUT_OF_PR`, `THROUGH_PR`, and `UNKNOWN` symmetrically.
- `STOCK` is not `FLOW`.
- Facility location is not economic ownership.
- Corporate parent is not beneficial owner unless independently bound.
- Tax incentive is not demonstrated net loss.
- Lobbying is not influence.
- Contribution is not quid pro quo.
- Macro aggregate is not company-specific flow.
- Sector aggregate is not company-specific flow.
- Sector GDP is not a direct-investment-profit allocation.
- Historical sector share is not current sector share.
- `UNKNOWN` is not zero.
- Require arithmetic closure at every decomposition layer.
- Historical policy evidence does not automatically prove current causal effect.
- Hard recipient/ownership evidence overrides geographic or corporate-profile inference.
- Lens Realignment is permitted only when empirical decomposition shows another metric better explains Puerto Rico capital retention.

## Public-source exhaustion before request escalation

Request/FOIA escalation is downstream of public-source exhaustion. A source family is not publicly exhausted while known authoritative downloadable manifestations, successor series, tables, workbooks, archives, or public data-center records remain uninspected. A tool-access or parser limitation is `BLOCKED`, not evidence that the source or requested field is absent.

## Measurement taxonomy

Every economic observation must classify its measurement type as one of:

- `FLOW`
- `STOCK`
- `RATE`
- `BALANCE`
- `VALUATION`
- `COUNT`
- `UNKNOWN`

Every Puerto Rico directional flow must classify as one of:

- `INTO_PR`
- `WITHIN_PR`
- `OUT_OF_PR`
- `THROUGH_PR`
- `UNKNOWN`

Economic residence is modeled separately from:

- facility location;
- legal domicile;
- tax residence;
- immediate parent;
- ultimate parent;
- beneficial owner;
- owner jurisdiction.

## Flow-observation minimum contract

A canonical or provisional flow observation should preserve, where source-supported:

- stable observation ID;
- source entity ID;
- destination entity ID;
- amount and currency;
- period start and period end;
- measurement type;
- economic category;
- Puerto Rico flow direction;
- source jurisdiction;
- destination jurisdiction;
- Puerto Rico retention state;
- source manifestation ID and source record ID;
- evidence/certification state;
- notes without overwriting raw source strings.

Null counterparties are allowed only when the source is genuinely aggregate or unresolved; they must not be silently imputed.

## GDP−GNP reconciliation

For each fiscal year, MoneySweep should preserve the reported macro aggregates and an explicit derived gap:

`GDP_GNP_GAP = GDP - GNP`

The gap is not automatically classified as capital transfer or U.S.-bound income. Decomposition is performed only through source-supported national/income-account components.

Each decomposition node must preserve:

- `total_amount`
- `classified_amount`
- `unclassified_amount`
- `currency`
- `period`
- `source_manifestation_id`
- `certification_state`

Invariant:

`total_amount = classified_amount + unclassified_amount`

No node may certify with unexplained arithmetic residue.

## Retention analysis

MoneySweep may derive retention metrics only for bounded denominators with sufficiently closed destinations.

`RETENTION_RATE = resident_retained_income / bounded_total_value`

`EXTERNAL_CAPTURE_RATE = nonresident_accrual / bounded_total_value`

When destination closure is insufficient, the metric remains `UNRESOLVED`; the system must not force an estimate.

## Existing verticals under V2

Existing domains remain first-class evidence layers:

- procurement and contracts;
- federal grants and recovery;
- disaster assistance;
- tax expenditures;
- debt and fiscal control;
- corporate ownership and capital control;
- lobbying and campaign finance;
- property and leases;
- infrastructure income;
- litigation;
- vendor penetration;
- municipality-level finance;
- agency reorganization;
- law-enforcement finance;
- geospatial enrichment.

These are not collapsed into one suspicion score. They bind to the capital-flow model only through explicit IDs and evidence-backed relationships.

## Federation boundary

MoneySweep owns financial-source ingestion, capital-flow reconciliation, public-finance analysis, and its own entity/ownership evidence. `thehub-pr` remains responsible for cross-producer federation aggregation and correlation.

## Certification boundary

A successful parser, join, visualization, or deterministic resolver does not certify an economic conclusion.

`CERTIFIED` requires, for the stated bounded scope:

- frozen source manifestations;
- explicit inclusion/exclusion rules;
- validated identities;
- preserved unresolved/tied candidates;
- row and amount conservation;
- no unintended join multiplication;
- arithmetic closure;
- source-to-output lineage;
- zero unresolved residue inside the certified claim.

Until those conditions are met, outputs remain `PASS` for implementation, `PROVISIONAL`, `AUDIT_ONLY`, `CANDIDATE_NOT_IDENTITY`, `UNRESOLVED`, or another explicitly defined non-certified state.

## Implementation sequence

1. Freeze this charter and schema enums.
2. Add a canonical capital-flow observation schema and regression gates.
3. Add annual macro-account schema and GDP−GNP arithmetic closure.
4. Build Puerto Rico macro ledger from authoritative source manifestations.
5. Decompose factor/property income into source-supported categories.
6. Exhaust authoritative current sector-profit manifestations before sector allocation; never use proxy shares as canonical allocations.
7. Bind sector and entity observations without forcing allocation of aggregates.
8. Reuse the existing capital-control graph for parent/owner adjudication.
9. Add retention metrics only after denominator and destination closure.
10. Connect tax incentives, lobbying, campaign finance, and policy downstream.
11. Add human-facing workflows only with full federation GUI parity.
