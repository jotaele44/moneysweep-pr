# PR #58 Enrichment Close-out — Delta Report

**Branch:** `claude/r5-pr58-enrichment-closeout`
**Date:** 2026-05-12

## USAspending UEI Lookup — Final Results

| Metric | Value |
|---|---|
| UEIs queried | 2,334 |
| Resolved in USAspending | 2,299 (98.5%) |
| parent_uei resolved | 434 (18.59%) |
| parent_uei not resolved | 1,900 (81.41%) |

The 81% with no parent are predominantly Puerto Rico government agencies (PRDOH, ADSEF, PRDE, PRHA, municipios) that do not register corporate parent UEIs in SAM/USAspending — structurally expected, not a data gap.

## Gate Changes

| Gate | Before | After | Status |
|---|---|---|---|
| `corporate_parent_uei_rate` | 0.0004 | **0.0032** | **PASS** (threshold 0.002) |
| `entity_type_assignment_rate` | 1.0000 | 1.0000 | PASS |
| `high_value_unresolved_review_rate` | 1.0000 | 1.0000 | PASS |
| `execution_chain_linkage_rate` | 0.5969 | 0.5969 | FAIL (awaits FSRS, PR #59) |
| `source_coverage_rate` | 0.5000 | 0.5000 | FAIL (awaits PR #59–65) |
| `failed_gate_count` | 115 | **114** | −1 gate |

## Outputs Refreshed

- `data/staging/processed/entities_resolved.csv` — 107,459 rows, 434 parent_ueis populated
- `data/staging/processed/high_value_unresolved.csv` — 3,618 rows (entities ≥$1M without parent)
- `data/staging/processed/execution/execution_chain_master.csv` — 640 chains (unchanged; linkage blocked by FSRS)
- `data/staging/processed/graphs/influence_graph.gexf` — refreshed parent_of edges
- `data/staging/processed/graphs/top_25_control_entities.csv` — refreshed
- `data/manifests/validation_report.json` — schema_version r5_v2

## Next

PR #59: Run `scripts/download_fsrs.py` → emit `pr_fsrs_subawards.csv` → push `execution_chain_linkage_rate` from 0.597 toward 0.90.
