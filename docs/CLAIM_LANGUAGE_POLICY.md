# CLAIM LANGUAGE POLICY

## Claim Classes
- `Observed`
- `Linked`
- `Inferred`
- `Risk signal`
- `Blocked / unvalidated`

## Allowed Language
- "record shows"
- "source states"
- "matched to"
- "linked with confidence X"
- "suggests"
- "indicates"
- "potential indicator"
- "requires review"
- "not validated"

## Forbidden Language
- "proves"
- "confirmed control"
- "secret operation"
- "definitive influence"
- "guaranteed environmental harm"

## Usage Rules
- Use probabilistic language for inferred or risk outputs.
- Tie each claim to source class and confidence context.
- If a gate fails, claims must be downgraded to blocked/unvalidated wording.
- Avoid conclusive language unless a claim is strictly observed and directly sourced.
- `COLLECTS_REVENUE` and `PLEDGED_TO_DEBT` edges are `Observed`/`Linked` when sourced
  from audited financials or EMMA disclosures, but `ALLOCATES_REVENUE_TO` edges are
  `Inferred` unless a line-item appropriation document is cited — collected revenue
  funding a specific contract is an inference, not an observed accounting trail.

## Tier Derivation (Maturity Gate)

`contract_sweeper/runtime/maturity_gate.py` translates the
`pipeline_status` column of `reports/source_registry_status.csv` into
the claim tiers above. When a claim depends on multiple datasets, the
worst tier wins.

| `pipeline_status`              | Derived `claim_tier` |
|--------------------------------|----------------------|
| `fully_materialized`           | `observed`           |
| `partially_materialized`       | `linked`             |
| `not_materialized`             | `blocked`            |
| `below_threshold`              | `blocked`            |
| `no_outputs_declared`          | `observed`           |
| *(source unknown to registry)* | `blocked`            |

Consumers:

- `scripts/influence_graph_builder.py` stamps every edge in
  `entity_edges.csv` with `claim_tier`, and propagates the worst
  incident-edge tier onto each node in `top_25_control_entities.csv`.
- `scripts/analyze_bond_flow.py` writes a `claim_tier` column on
  `pr_bond_flow.csv` so EMMA/MSRB-dependent rows carry the gate result.
- `scripts/generate_report.py` prepends a `_Claim tier: …_` marker to
  every section and exposes `claim_tiers` in `pr_report_summary.json`.
