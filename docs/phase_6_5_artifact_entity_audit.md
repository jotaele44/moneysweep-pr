# Phase 6.5 Artifact And Entity Audit

Date: 2026-05-08

## Status

Current checked-in outputs are marked `NON_PRODUCTION_DIAGNOSTIC`.

Graph rebuild is blocked.

Risk engine execution is blocked.

## Key Findings

| Metric | Observed | Gate |
| --- | ---: | ---: |
| unique_normalized_entity_count | 18 | >=100 |
| entity_resolution_rate | 0.00 | >=0.95 |
| parent_uei_coverage | 0.00 | >=0.90 |
| report_layers_populated | 3 | >=8 |
| bond_actor_count | 0 | >0 |
| high_value_overcollapse_suspect_count | 18 | 0 |
| self_pair_ratio | 0.10 | <0.05 |
| dense_matrix_score | 0.8272 | manual review |

## Stale Artifact Signals

- `generate_report.py` returns `CACHED` if `pr_investigative_report.md` exists and `--force` is not passed.
- `build_unified_master.py` skips existing `pr_all_awards_master.csv` unless `--force` is passed.
- `run_all.py --skip-download` does not enforce downstream force rebuilds, so it can replay cached exports.
- The report summary still carries `generated_at = 2026-05-04 07:05 UTC`.
- Several committed summary files embed `/home/user/Contract-Sweeper` output paths, which do not match this worktree.

## Required Outputs

- `data/exports/output_validation_audit.json`
- `data/exports/entity_universe_audit.csv`
- `data/exports/entity_collapse_diagnostics.csv`
- `data/exports/artifact_lineage_audit.csv`
- `data/exports/cache_reuse_audit.csv`
- `data/review_queue/suspect_entity_collapses.csv`
- `data/review_queue/graph_coverage_blockers.csv`

## Decision

Do not rebuild graph.

Do not run the risk engine.

Rebuild the entity universe only after stale artifact replay, fixture/synthetic fallback paths, parent UEI coverage, and bond actor ingestion are corrected.
