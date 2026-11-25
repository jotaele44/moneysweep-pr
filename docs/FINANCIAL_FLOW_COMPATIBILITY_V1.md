# MoneySweep Financial Flow Compatibility V1 — bounded adapter

## Parent and scope

Dependency: PR #712 / Financial Classification V1, head `96c792351c8d257b3901c2aeeb1c10dad11a257c` when this candidate was branched. This is a **stacked candidate**, not a production promotion.

Source: `scripts/build_financial_flows_master.py` emits `data/normalized/financial_flows_master.parquet`. The existing output contains randomly generated `flow_id` values, source-system labels and loosely typed `amount_type` values; it does not independently establish authoritative source-native row identities, original source SHA-256 hashes, nor consistent accounting basis, currency, or period.

**Do not** treat `flow_id` as a durable financial identity. Do not interpret `total_amount` as an unduplicated disbursement or expenditure total. The legacy builder sums different financial stages, revenue and sometimes overlapping award scopes.

## Additive contract

`moneysweep.financial_flow_compatibility_v1.adapt_legacy_flows(rows, bindings, expected_flow_ids)`

- Takes an in-memory, frozen legacy row inventory and an explicit expected legacy-ID set.
- Rejects missing, duplicate, or unexpected legacy rows and references to nonexistent rows.
- Leaves rows without a reviewed binding in an `UNRESOLVED` output without constructing a zero-valued observation.
- Requires each bound row to specify source-native identity, original source byte SHA, source version and field, accounting measure, period, basis, currency, and scope.
- Checks legacy source system, file, amount type and exact-Decimal amount against the supplied binding.
- Uses Financial Classification V1 to create deterministic, separately namespaced observation IDs.
- Rejects duplicate canonical observations within the bounded manifestation.
- Does not change or write any legacy export, source record, amount, identifier or existing API.
- Always returns `source_universe_certified=false` and `promotion_authorized=false`.

The binding object is a *claim* about authoritative evidence, not cryptographic verification of the source file. Production integrations must independently verify the original bytes, hash, row identifier, extraction logic, period, and source-native measure semantics before passing a binding to this adapter.

## Measure classification

No blanket `amount_type` to `measure_type` mapping is authorized here:

| Legacy amount_type | Default classification | Reason |
|---|---|---|
| `federal_share_obligated` | UNRESOLVED until source binding | Source context and effective period required |
| `obligated_amount` | UNRESOLVED until source binding | Award state and amendment semantics required |
| `grant_amount` | UNRESOLVED | Could reflect allocation, award or budget |
| `activity_budget` | UNRESOLVED | Budget is not automatically disbursement |
| `drawdown` | UNRESOLVED | A drawdown is not necessarily a recipient payment |
| `total_approved` | UNRESOLVED | Approval is not automatically an obligation |
| `contract_value` | UNRESOLVED | Ceiling/value is not automatically obligated |
| `gross_revenue` | UNRESOLVED | Revenue requires domain-specific accounting classification |

Only an independently verified and reviewed source binding can resolve one of these classifications.

## Gate boundary

This primitive does **not** establish source completeness, real-money disbursement, ultimate disposition, a financial-event ledger, transaction conservation, a deterministic source manifest, source acquisition, post-merge replay, or a simulation model. All remain OPEN.

Execution path: `python -m pytest tests/test_financial_flow_compatibility_v1.py -v` and repository CI. The independent approver must validate original-source receipt semantics and the reconciliation boundary.

When PR #712 merges, this PR must be retargeted/reconciled against the *actual merged head* and its regression gates rerun; never infer merge qualification from the parent PR's checks.
