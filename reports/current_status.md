# Current Status — R5 PR2.5

**Updated:** 2026-05-12  
**Branch:** `claude/r5-pr2-top5-source-materialization`  
**Phase:** PR2.5 — USAspending parent enrichment + structural blocker report

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
- 0.0009% parent-resolved (1 self-referential; 0 distinct corporate parents)
- 3,818 entities with total_obligation ≥ $1M require manual review
- **Structural finding:** Top entities by obligation are PR government agencies — no corporate parent_uei expected
- USAspending lookup running in background (~7h ETA); will refresh once complete
- Gate recalibration recommended: `parent_uei_rate ≥ 0.05` for PR govt sources (was 0.90)

## PR2.5 outputs

| Output | Status |
|---|---|
| `scripts/parent_collapse.py` USAspending index patch | ✓ |
| `data/processed/entities_resolved_top5.csv` | ✓ 5 rows |
| `data/processed/alias_registry_top5.json` | ✓ 5 entries |
| `data/review_queue/pr2_unresolved_entities.csv` | ✓ 3,818 rows |
| `reports/pr2_5_sam_parent_resolution_report.md` | ✓ written |
| Tests (PR2-specific): 11 passed | ✓ |
| Secret scan | ✓ 0 findings |
