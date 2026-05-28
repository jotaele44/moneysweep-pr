# PR Intake Router Execution

## Purpose

The PR intake router is the shared zero-loss routing layer for Puerto Rico raw intake items. It classifies raw observations and emits derivative records for:

- `Contract-Sweeper`: politics, finance, public funding, contracts, procurement, lobbying, budgets, municipal finance.
- `spiderweb-pr`: geography, GIS, infrastructure footprint, subsurface/hydro, aviation, maritime, federal/military activity, environment, weather, science.

## Primary command

```bash
python run_pr_intake_router.py --input tests/fixtures/pr_intake_router_sample.jsonl --out-dir data/exports/pr_intake_router
```

Equivalent command:

```bash
python scripts/route_pr_intake.py --input tests/fixtures/pr_intake_router_sample.jsonl --out-dir data/exports/pr_intake_router
```

## Strict validation mode

```bash
python run_pr_intake_router.py --input tests/fixtures/pr_intake_router_sample.jsonl --out-dir data/exports/pr_intake_router --fail-on-validation-errors
```

Use `--strict` only when you want the first invalid record to abort immediately.

## Outputs

The router writes:

- `route_results.jsonl`
- `contract_sweeper_derivatives.csv`
- `spiderweb_pr_derivatives.csv`
- `manual_review_queue.csv`
- `routing_summary.json`

## Daily PR News integration point

When a future PR News intake module writes normalized raw observations, place them at:

```text
data/intake/pr_news/raw_items_latest.jsonl
```

Then run:

```bash
python run_pr_intake_router.py --input data/intake/pr_news/raw_items_latest.jsonl --out-dir data/exports/pr_intake_router
```

## Validation invariant

Every raw item must receive one final status:

- `routed_contract_sweeper`
- `routed_spiderweb_pr`
- `dual_routed_contract_primary`
- `dual_routed_spiderweb_primary`
- `duplicate_consolidated`
- `not_relevant_with_reason`
- `manual_review_required`
- `source_inaccessible`
- `blocked_or_paywalled`
- `metadata_only_archived`

No item may disappear between raw intake and derivative export.
