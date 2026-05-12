# PR3 Execution Chain Builder — Delta Report

**Branch:** `claude/r5-pr3-execution-chains`
**Date:** 2026-05-12

## Results

| Metric | Value |
|---|---|
| chain_count | 640 |
| linked_to_prime | 382 |
| linkage_rate | 0.597 (59.7%) |
| full_chain_rate | 0.597 |
| review_queue_count | 639 |
| per_asset_count | 0 |
| per_municipality_count | 2 |

## Gate Status

| Gate | Observed | Threshold | Result |
|---|---|---|---|
| execution_chain_linkage_rate | 0.597 | 0.90 | FAIL (expected) |
| entity_type_assignment_rate | 1.000 | 0.80 | PASS |
| high_value_unresolved_review_rate | 1.000 | 0.90 | PASS |
| corporate_parent_uei_rate | 0.0004 | 0.002 | FAIL (enrichment in progress) |

## Structural Notes

**Linkage rate 59.7%:** `pr_subawards_master.csv` (382 rows) links via `prime_award_id` → 382 prime-linked chains. The remaining 258 rows from `pr_prime_sub_relationships.csv` are aggregate summaries (no individual `prime_award_id`) → classified as `subaward_record_only`. Gate threshold of 0.90 is aspirational; realistic target once FSRS is fully ingested.

**per_asset_count = 0:** Subaward records contain no `asset_id`, `facility_id`, or `project_number` fields. Asset linkage is deferred to PR4 (assets_master).

**per_municipality_count = 2:** Current subaward data has `pop_county` populated for only 2 distinct values. Full municipality coverage depends on FEMA PA and COR3 ingestion (PR5+).

## Outputs

- `data/staging/processed/execution/execution_chain_master.csv` — 640 rows
- `data/staging/processed/execution/execution_chain_per_asset.csv` — 0 rows (no asset_id in source data)
- `data/staging/processed/execution/execution_chain_per_municipality.csv` — 2 rows
- `data/staging/processed/execution/execution_chain_review_queue.csv` — 639 rows (conf < 0.90)

## Next

PR4: influence graph + top_25_control_entities using `entities_resolved.csv` + `execution_chain_master.csv`.
