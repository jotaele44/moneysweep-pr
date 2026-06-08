# Cross-repo intake-lane delivery (#114 / #41)

How Puerto Rico politics/finance and spatial/operational records flow from the
shared PR-intake router into each repo's normalized lane.

## The chain

```
raw intake items (JSONL/JSON/CSV)
  └─ scripts/route_pr_intake.py            # shared/pr_intake_router.py + config/pr_intake_domain_router.yaml
       ├─ data/exports/pr_intake_router/contract_sweeper_derivatives.csv
       │    └─ scripts/build_contract_sweeper_finance_lane.py   (this repo, #114)
       │         → data/normalized/{funding_event_leads, contracts_procurement_events,
       │            politics_finance_items, agency_actions, lobbying_political_links}.csv
       │         + data/review/{verification_queue, contract_sweeper_crosswalk_queue,
       │            discrepancy_queue}.csv
       └─ data/exports/pr_intake_router/spiderweb_pr_derivatives.csv
            └─ scripts/deliver_derivatives.py  → spiderweb-pr/data/intake/pr_intake/
                 └─ spiderweb-pr scripts/build_spiderweb_spatial_lane.py  (#41)
                      → spiderweb-pr/data/normalized/*.csv
```

The finance lane fans each derivative out into exactly the tables the router
assigned via the row's `output_tables` field. It is **zero-loss**: every input
row lands in ≥1 normalized table or review queue, or is recorded in
`discrepancy_queue.csv` — nothing is dropped.

## Run it locally

```bash
python3 scripts/route_pr_intake.py --input tests/fixtures/pr_intake_router_sample.jsonl \
        --out-dir data/exports/pr_intake_router
python3 scripts/build_contract_sweeper_finance_lane.py --input data/exports/pr_intake_router --out .
python3 scripts/deliver_derivatives.py --derivatives-dir data/exports/pr_intake_router \
        --dropzone ../spiderweb-pr/data/intake/pr_intake
# then, in spiderweb-pr:
python3 scripts/build_spiderweb_spatial_lane.py --input data/intake/pr_intake
```

## Automation

`.github/workflows/intake-delivery.yml` (manual `workflow_dispatch`) runs the
chain and opens PRs. Two delivery hops:

- **Same-repo** finance-lane PR — uses the default `GITHUB_TOKEN`.
- **Cross-repo** delivery to `spiderweb-pr` — needs a **`FEDERATION_DELIVERY_TOKEN`**
  repository secret: a `repo`-scoped PAT with write access to
  `jotaele44/spiderweb-pr` (the default Actions token is single-repo). When the
  secret is absent the cross-repo step is skipped.

> The workflow is delivery scaffolding and is **not** exercised by CI (it cannot
> open a real cross-repo PR without the PAT). The logic it calls **is** covered:
> `tests/test_contract_sweeper_finance_lane.py` and `tests/test_deliver_derivatives.py`.
