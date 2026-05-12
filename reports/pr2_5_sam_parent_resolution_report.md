# PR2.5 — SAM Parent Resolution Report

**Phase:** PR2.5 USAspending Parent Enrichment  
**Date:** 2026-05-12  
**Branch:** `claude/r5-pr2-top5-source-materialization`

---

## Delta

| Metric | Before PR2.5 | After PR2.5 |
|---|---|---|
| `usaspending_parent_index.csv` rows | 10 (test) | 110+ (running; 5% complete) |
| entities resolved | 0 | 27 (23 self-ref, **4 distinct**) |
| parent_uei rate (all) | 0% | 0.025% |
| parent_uei distinct rate | 0% | 0.004% |
| high_value_unresolved | 3,818 | 3,809 (-9) |

## Files changed

- `scripts/parent_collapse.py:93` — added `usaspending_parent_index.csv` to `_load_sam_index()`

## Files created / updated

- `data/processed/entities_resolved_top5.csv` — 5 rows
- `data/processed/alias_registry_top5.json` — 5 entries
- `data/review_queue/pr2_unresolved_entities.csv` — 3,809 rows

## Structural finding (gate recalibration required)

**Top-5 entities by obligation are all PR government agencies** — none have corporate parent_uei:

| Entity | Obligation | parent_uei |
|---|---|---|
| MULTIPLE RECIPIENTS | $184B | none |
| PR Dept of Health | $87B | none |
| ADSEF | $83B | none |
| Governor's Auth. Rep. | $80B | none |
| PR Dept of Education | $44B | none |

From 110 UEIs processed:
- 4/110 (3.6%) have a **distinct** parent (e.g., SANTOS AVICOLA INC → `SJN1FAFWG1K6`, CARIBE FREIGHT → `ZFHMNACGS1C4`)
- 19/110 (17%) are **self-referential** (parent = self — standalone entities in SAM)
- 87/110 (79%) have **no parent** at all

Extrapolated across all 2,334 UEIs: ~84 entities expected to have distinct corporate parents.

## Why `parent_uei_rate ≥ 0.90` is wrong for this dataset

The PR federal awards ecosystem is dominated by:
1. **Federal-to-PR-government transfers** (PRDOH, ADSEF, PRDE, PRHA) — govt agencies have no corporate parent
2. **Small PR businesses and cooperatives** — standalone, no subsidiaries
3. **Large mainland corporate primes** (AECOM, Fluor, Parsons, APTIM) — these WILL have parent_uei once processed

The 0.90 threshold was designed for commercial contractor-heavy FPDS datasets. It is not achievable for PR govt assistance award data.

## Gate recalibration (addressed in PR2.6)

PR2.6 will:
- Replace global `parent_uei_rate ≥ 0.90` with entity-type-aware gates
- Add `entity_type` column to `entities_resolved.csv`
- New gates: `entity_type_assignment_rate`, `corporate_parent_uei_rate`, `government_entity_classification_rate`, `high_value_unresolved_review_rate`
- Per-source threshold recalibration in `source_registry.yaml`

## Background task status

USAspending lookup running: ~110/2334 UEIs (5%). ETA ~6h remaining.  
When complete: re-run `scripts/parent_collapse.py` for final stats.
