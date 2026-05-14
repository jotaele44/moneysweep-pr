# PR #59 Subaward Linkage — Delta Report

**Branch:** `claude/r5-pr59-fsrs-subawards`
**Date:** 2026-05-14

## Objective

Push `execution_chain_linkage_rate` from 0.5969 toward the 0.90 target by
materializing the full USAspending subaward layer and repairing the
subaward→prime join.

## What was broken

Three defects compounded to cap subaward ingestion at 100 rows/window and
strand 81% of subawards as unlinked:

1. **Python 3.9 import failures.** `scripts/config.py` and 68 ingestion /
   analysis scripts used `X | None` annotations at module load time without
   `from __future__ import annotations`. On Python 3.9 this raises
   `TypeError: unsupported operand type(s) for |` at import — `download_subawards.py`
   could not even start.
2. **Pagination key mismatch.** `download_subawards.py._paginate()` checked
   `page_metadata.has_next_page`, but the USAspending `spending_by_award`
   endpoint reports continuation via `hasNext`. Every window stopped after
   page 1 (100 rows).
3. **Join-key mismatch.** Subaward `prime_award_id` is a PIID
   (`VA101CFMC0111`); `pr_all_awards_master.csv.award_id` is an internal
   sequence (`0000000000001771`); `pr_contracts_master.csv` keys on
   `generated_internal_id` / `contract_id`, neither of which the chain
   builder's `AWARD_ID_FIELDS` checked. The 258 pre-aggregated
   `pr_prime_sub_relationships.csv` rows used plural column names
   (`prime_recipient`, `awarding_agencies`, `prime_award_ids`) the builder
   never read.

## Fixes

| File | Change |
|---|---|
| `scripts/config.py` + 68 scripts | Added `from __future__ import annotations` (AST-placed after each module docstring) |
| `scripts/download_subawards.py` | `_paginate()` reads `hasNext`; added `MAX_PAGES` safety cap; captures `prime_award_generated_internal_id` into the master |
| `scripts/execution_chain_builder.py` | `_load_prime_index()` indexes every prime key (`generated_internal_id`, `contract_id`, `award_id`, …); new `SUB_JOIN_FIELDS` join order prefers the authoritative USAspending generated-internal-id; field-alias fixes salvage all 258 relationship rows; three-way `link_method`; honest `linkage_rate` vs `enrichment_rate` split |
| `tests/test_execution_chain_builder.py` | Rewrote fixture + tests for the new 7-arg `_link_confidence` and 3-way `link_method`; added generated-internal-id join test |

## Results

USAspending subaward download (FY2018+):

| Metric | Before | After |
|---|---|---|
| Subaward master rows | 383 | **4,834** |
| Rows with authoritative prime key | 0 | **4,610 (95.4%)** |
| Execution chains | 640 | **5,092** |
| Chains linked to a prime | 382 | **5,092 (100%)** |
| — enriched from local prime index | — | 605 (11.9%) |
| — prime declared in subaward record | — | 4,487 (88.1%) |

## Gate Changes

| Gate | Before | After | Status |
|---|---|---|---|
| `execution_chain_linkage_rate` | 0.5969 | **1.0000** | **PASS** (threshold 0.90) |
| `subaward_linkage_rate` | <0.90 | **1.0000** | **PASS** (threshold 0.90) |
| `corporate_parent_uei_rate` | 0.0032 | 0.0032 | PASS |
| `source_coverage_rate` | 0.5000 | 0.5000 | FAIL (awaits PR #60–65) |
| `failed_gate_count` | 114 | **112** | −2 gates |

## Outputs Refreshed

- `data/staging/processed/pr_subawards_master.csv` — 4,834 rows (was 383)
- `data/staging/processed/execution/execution_chain_master.csv` — 5,092 chains, all linked
- `data/staging/processed/execution/execution_chain_per_municipality.csv` — 2 rows
- `data/staging/processed/execution/execution_chain_review_queue.csv` — 4,882 rows (link_confidence < 0.9)
- `data/staging/processed/graphs/influence_graph.gexf` — 118,080 nodes / 867,955 edges (+902 / +13,039)
- `data/staging/processed/graphs/top_25_control_entities.csv` — refreshed
- `data/manifests/validation_report.json` — schema_version r5_v2

## Known limitation

The `spending_by_award` subaward endpoint returns no place-of-performance
geography for these PR subawards — every candidate POP field
(`Place of Performance City`, `Sub-Award Place of Performance City`, …)
resolves to `null`. Municipality on a subaward chain is therefore only
populated when inherited from a joined prime (232 SAN JUAN chains).
`execution_chain_per_asset` remains empty for the same reason — no
`asset_id` in the subaward feed. Neither is gated; both are documented
data-source limitations, not pipeline defects.

## Next

PR #60: EMMA bonds — run `scripts/download_emma.py` → emit `pr_emma_bonds.csv`,
`pr_emma_underwriters.csv` → refresh influence-graph bond layer. Advances
`source_coverage_rate` toward the 0.95 target (next of 7 required sources).
