# Financial Classification V1 — source applicability and readiness

Issue: #695. Candidate branch: `feature/financial-classification-v1-695`.

## Snapshot baseline, not certification

Observed repository default-branch SHA during investigation:
`c478c3a00d87d51e062df40f9be126d089416822`.

`reports/financial_source_audit.md` at the observed baseline reports 167 registry entries, of which 158 financial and 9 reference/supporting, plus 5 not-yet-considered candidate sources. It is a **historical audit**, not a current immutable inventory and not a denominator of materialized source records. The current **source, dataset and row denominators are OPEN**.

## Coverage vector (every item must be enumerated before 100% certification)

| Family | Existing evidence | V1 measure candidate | Source-level readiness | Row classification |
|---|---|---|---|---|
| Federal obligations/outlays | `registries/schema_registry.json` | OBLIGATED / OUTLAY | DISCOVERED | OPEN |
| FEMA PA | `scripts/build_financial_flows_master.py` | obligation and project amounts; source semantics to adjudicate | DISCOVERED | OPEN |
| HUD DRGR | `scripts/build_financial_flows_master.py` | budget, drawdown; drawdown not assumed equal payment | DISCOVERED | OPEN |
| COR3 | `scripts/ingest_cor3.py`, `scripts/download_cor3.py` | APPROVED vs DISBURSED; approval not presumed obligation | DISCOVERED | OPEN |
| SF-133 budget execution | `scripts/download_sf133.py` | budget authority / obligation / outlay | DISCOVERED | OPEN |
| Procurement/municipal | `scripts/config.py`, financial flow builder | award, obligation, expenditure depending on native fields | DISCOVERED | OPEN |
| Political financing | `docs/POLITICAL_FINANCE_FLOW_GRAPH.md` | receipts and payments, not federal appropriations by default | DISCOVERED | OPEN |
| Debt / revenue | source audit finance domains | proceeds, debt service, rate revenue: require domain-specific types | DISCOVERED | OPEN |

No row-level state or numeric measure is inferred from this matrix. Sources not yet inspected also require explicit entries; this is **not** the full source inventory.

## Mandatory pre-execution source manifest

Freeze for every source: source registry ID, authoritative URL/service/layer/query, retrieval UTC, version/refresh, original byte SHA256, byte length, parser code SHA, schema/header and row count, pagination completeness, status, inclusion/exclusion rationale, and per-row source identity. Preserve alternate manifestations separately. A source marked `queued_manual`, `wired_needs_key`, or `wired_ready_unmaterialized` is **not** a successfully populated source.

Applicability matrix unique grain is `source_snapshot × source_record_identity × measure_type`. A row may have multiple valid measures; the row-denominator and measure-denominator must be reported separately. Unidentified row keys, collisions, repeated revisions, M:N ambiguity, missing bytes and temporal conflicts remain `UNRESOLVED`. No silent join by agency/recipient name.

## Production integration gates

1. Maintain existing export stream schemas and IDs. The new module generates a separate namespaced observation ID, without replacing random legacy flow IDs in situ.
2. Define source-specific mappings and authoritative accounting semantics. `APPROVED`, `OBLIGATED`, `DISBURSED`, `OUTLAY`, `EXPENDED` are not synonyms.
3. Input manifests and source record IDs must be stable and independently evidenced. Snapshot data must not be summed with its own action log.
4. Require complete source-level AND row-level denominators, conservation, explicit non-applicability, valid identifiers, source hashes, and negative/adversarial tests.
5. Independently review, verify exact-head CI, merge only when approved, replay merged head, obtain TheHub LOCKSTEP, freeze receipts, then promote reusable skill.

**Current certification: WITHHELD.** This branch implements a bounded validation primitive, not a comprehensive historical backfill or completed financial source audit.


## Current-head reconciliation — 2026-11-12

The original V1 candidate was reviewed on PR #696 at head `012d2cea3840d3a42e60da4e59c23b1eb98ced60`. The successor candidate is rebased additively onto current default-branch SHA `b0dc1737fb58b4c544c1189a8db7e43338b70188` without changing legacy financial-flow exports. The original historical baseline above is retained as historical evidence and is not rewritten.

This rebase does not close source, row, event, identity, payment-chain, or ultimate-disposition denominators. It does not implement a complete financial-event ledger, simulations, or counterfactual analysis. All such capabilities remain outside V1 and require separately versioned contracts and verification.

PR #696 remains open and draft pending qualification of this successor. No merge, production promotion, or certification is authorized by this rebase.
