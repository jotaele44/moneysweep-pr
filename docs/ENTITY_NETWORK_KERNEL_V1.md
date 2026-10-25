# MoneySweep Entity-Network Kernel v1

**Status:** additive internal infrastructure  
**Baseline main:** `c972f7a956f4126faffd5f47a5f54a6c8ebd2fd1`  
**Scope:** behavior before population; no MII entity promotion and no new GUI surface.

## Frozen reference inputs

The design/research reference used for this bootstrap is MII v0.3.

- `PR ecosystem network · MII v0.3.pdf`
  - SHA-256: `4e99ddb6efa80ef36909429f27a315064367c57449ad1e4f9dcc301d802925b3`
- `PR ecosystem network · MII v0.3.zip`
  - SHA-256: `cd55c56785d5e8258f4cc5b9d5a5dcb8541c7e183e33a49f6a60430ecb34725d`
  - six members: `Main.dc.html`, `ds/pr-int/styles.css`, `support.js`,
    `vendor/react.js`, `vendor/react-dom.js`, and `README.md`.

The ZIP README labels the export a design reference mockup rather than production
code. This change therefore uses its ecosystem organization as a behavioral
reference and does not copy its runtime into MoneySweep.

## Why this layer is additive

MoneySweep already has strong primitives that remain authoritative:

- `moneysweep.capital_control.resolution_core` provides candidate preservation,
  evidence priority, certification states, cardinality, contradiction handling,
  and fail-closed M:N join guards.
- `moneysweep.entity_resolution` provides existing identifier/scoring adapters.
- Existing federation schemas and `canonical_v1` schemas are compatibility
  surfaces and are not modified by this change.

The entity-network kernel composes those controls. It does **not** create a second
entity-resolution engine.

## Canonical ingestion behavior

```text
SOURCE_MANIFESTATION
  -> CANDIDATE DISCOVERY
  -> resolution_core identity adjudication
  -> canonical entity reference
  -> N:N sector membership
  -> typed non-monetary relationship assertion
  -> separate money-flow observation
  -> downstream graph projections
```

Adapters may discover candidates. They may not use name-only, normalized-name,
same-sector, proximity, count equality, or deterministic selection as identity
proof.

## Core invariants

1. Source manifestation != canonical entity.
2. Entity != facility.
3. Sector membership is N:N and is not identity evidence.
4. Dependency != money flow.
5. Parent != beneficial owner.
6. Unknown amount remains null; it is never rewritten as zero.
7. Tied top identity evidence remains UNRESOLVED.
8. Exact duplicate sector-membership observations fail closed.
9. Unintended many-to-many joins fail closed.
10. Existing frozen export schemas remain unchanged.

## Sector denominator

The initial profile denominator is 15 sectors:

1. Pharma, Biotech & Medical Devices
2. Aerospace & Defense
3. Energy, Fuels & Grid
4. Water, Wastewater & Environment
5. Ports, Airports, Roads & Maritime
6. Telecom, Cables & Space Communications
7. Industrial Manufacturing, EPC & Construction
8. Governance, Public Finance & Oversight
9. Research, Academia & Workforce
10. Healthcare Delivery, Payers & Pharmacy
11. Banking, Insurance & Private Finance
12. Real Estate, Tourism & Hospitality
13. Retail, Wholesale & Consumer Distribution
14. Technology, IT/BPO & Professional Services
15. Agriculture, Food & Beverage

Sector IDs are stable enum values. Renaming display labels must not mutate those IDs.

## Money-flow boundary

Ordinary graph relationships intentionally exclude direct money-movement verbs.
Payments, disbursements, obligations, reimbursements, investments, loans,
distributions, dividends, fees, and purchases belong to `MoneyFlowObservation`.

This prevents structural relationships such as `DEPENDENCY_ON` from silently
becoming evidence of payment.

## Current completion state

### PASS in this slice

- kernel primitives defined;
- 15-sector denominator defined;
- relationship vs money-flow boundary defined;
- existing resolution core reused;
- tied/heuristic identity behavior regression-tested;
- N:N sector membership preserved;
- unsafe M:N joins rejected;
- UNKNOWN amount behavior regression-tested.

### OPEN after this slice

- ingest MII v0.3 nodes/edges as provisional source manifestations;
- bind sector profiles to specific source adapters;
- add temporal beneficial-owner traversal;
- add sector coverage/exhaustion materialization;
- add API/UI only after backend semantics are stable;
- run authoritative source-expansion vectors before any completeness claim.
