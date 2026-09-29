# PR500 / Top-50 pre-ranking pilot certification

Status: **BLOCKED — no ranking publication authorized**

Branch: `gpt/pr500-ranking-eligibility-v1`
Base reviewed: `e26183342f0971010341185fab92b5d5f2ed94e2`

## Certification rule

A source observation is rank-eligible only after stable identity/binding, non-synthetic provenance, source snapshot hash, named metric, numeric value, unit, period bounds, and geographic scope are explicit. Missing evidence is not inferred from names, row position, source presence, or normalized-name similarity.

## Pilot 1 — Puerto Rico procurement / OCPR

**Result: BLOCKED for entity ranking.**

The live OCPR scraper produces contract number, contractor name, agency, amount, dates, service fields, document URL, and source file, but its own contract states that public scraped rows leave `contractor_id` blank because public SSNs are redacted. The canonical contract schema also makes `contractor_entity_id` optional. Therefore a contractor name is a discovery lead, not a certified entity binding. In addition, the current ranking gate requires source snapshot hash and explicit metric semantics before aggregation.

Required closure: resolve each contractor occurrence to a stable legal-entity identifier using authoritative evidence; retain unresolved candidate sets; attach immutable source-snapshot provenance; adjudicate amendments/co-contractors/duplicate financial events before aggregation.

## Pilot 2 — banking and credit unions / FDIC + NCUA

**Result: BLOCKED for publication; safeguards implemented.**

FDIC and NCUA downloader outputs now carry explicit `origin` and `financial_scope`. Fallback rows are labeled `FALLBACK_SEED` and are ineligible under the ranking gate. FDIC observations are labeled `INSTITUTION_WIDE`. NCUA institution seeds are `INSTITUTION_WIDE`; the `ALL_PR` row is explicitly `AGGREGATE_STATEWIDE`.

The committed NCUA ingest manifest dated 2026-06-17 reports four rows and hash `8aeef1eb4802be442b8b93ed90fbe47deac5bdf5fb3f0d3e7e7cc3b1f07d31d9`. Those four rows correspond to the downloader's fallback seed set, so that snapshot is not accepted as authoritative financial evidence for ranking. The financial-source audit also classifies FDIC and NCUA as not materialized in the guide audit view.

Required closure: materialize current authoritative FDIC/NCUA data, persist source snapshot hashes, prove stable institution identifiers, define period/unit semantics, and exclude aggregate rows from entity universes.

## Pilot 3 — Federal Audit Clearinghouse

**Result: BLOCKED for publication; destructive-empty safeguard implemented.**

The FAC producer exposes auditee EIN, audit year/fiscal end, total amount expended, findings count, and auditor. A forced zero-row fetch now preserves a prior non-empty snapshot and otherwise writes no fabricated header-only evidence file. However, the guide audit classifies `federal_audit_clearinghouse` as not materialized, while the broader financial-source audit identifies it as key-gated. The current row schema also does not carry an immutable snapshot hash into the ranking observation.

Required closure: obtain a successful authoritative FAC materialization, bind auditees through EIN or another stable identifier with explicit identity state, attach snapshot hash and metric semantics, and distinguish federal expenditures from awards/obligations rather than combining them.

## Gate result

| Gate | Procurement | Banking / CU | FAC |
| --- | --- | --- | --- |
| Stable entity identity | BLOCKED | PARTIAL | PARTIAL |
| Non-synthetic provenance | PARTIAL | BLOCKED for committed NCUA seed snapshot | BLOCKED pending materialization |
| Metric/unit/period/scope | PARTIAL | PARTIAL | PARTIAL |
| Immutable snapshot provenance | BLOCKED | PARTIAL | BLOCKED |
| Duplicate/flow adjudication | BLOCKED | N/A before ranking | N/A before ranking |
| Rank publication | BLOCKED | BLOCKED | BLOCKED |

## Decision

The eligibility mechanism is suitable for continued integration, but the evidence universe is **not pre-ranking certified**. No Top 500 or Top 50 cutoff should be computed or published from these pilot inputs yet. This is an evidence-availability result, not a claim that the underlying entities or sources are unreliable.
