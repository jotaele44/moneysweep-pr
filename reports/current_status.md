# Current Status — R5 PR2

**Updated:** 2026-05-12  
**Branch:** `claude/r5-pr2-top5-source-materialization`  
**Phase:** PR2 — Entity baseline + per-source manifests

## Outputs produced this PR

| Output | Rows | Status |
|---|---|---|
| `data/staging/processed/entities_resolved.csv` | 107,459 | ✓ written |
| `data/staging/processed/high_value_unresolved.csv` | 3,818 | ✓ written |
| `data/staging/processed/parent_conflict_queue.csv` | 0 | ✓ written |
| `data/staging/processed/enrichment/alias_registry.json` | 105,323 entries | ✓ written |
| `data/manifests/usaspending_prime/<ts>.json` | — | ✓ written |
| `data/manifests/fema_pa_openfema_v2/<ts>.json` | — | ✓ written |
| `data/manifests/lda/<ts>.json` | — | ✓ written |
| `data/manifests/fec/<ts>.json` | — | ✓ written |
| `data/manifests/sam_entities/<ts>.json` | — | ✓ written |

## Validation gate status

| Gate | Status | Note |
|---|---|---|
| source_coverage (5 top sources) | PASS (per-source) | Each of 5 has ≥1 non-empty output |
| source_coverage_rate (overall) | FAIL | 5/14 required = 36%; threshold 95% — expected until PR5 |
| entity_resolution_rate | FAIL | 0% parent-resolved; full SAM extract needed |
| parent_uei_rate | FAIL | 0%; full SAM extract needed |
| high_value_unresolved_zero | FAIL | 3,818 high-value entities unresolved |
| manifest_present_per_required | PARTIAL | 5/14 manifests now present |
| secret_leakage | PASS | 0 findings |

## Entity resolution baseline

- 107,459 unique entities observed across all staged CSVs
- 0% parent-resolved (vendor_uei_index.csv has 200 cached rows, no parent_uei filled)
- 3,818 entities with total_obligation ≥ $1M require manual review
- Resolution will improve when: (a) full SAM API extract runs, (b) PR contracts master is enriched
