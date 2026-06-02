# Canonical v1 Graph Summary

**Gate:** `NON_PRODUCTION_DIAGNOSTIC` · **Generated:** 2026-06-02T19:39:40.529924+00:00

_Descriptive, derived summary of the committed canonical_v1 tables. Asserts no new sourced claims; every figure is a count over existing, evidence-backed rows. Phrasing follows `docs/CLAIM_LANGUAGE_POLICY.md`._

## Nodes (199 total)

| Table | Count |
|-------|-------|
| `people` | 60 |
| `entities` | 22 |
| `roles` | 7 |
| `contracts` | 3 |
| `projects` | 5 |
| `debt_instruments` | 20 |
| `lobbying_records` | 0 |
| `funding_sources` | 4 |
| `properties` | 0 |
| `municipalities` | 78 |

## Edges (57 total)

| edge_type | Count |
|-----------|-------|
| `ADVISES` | 5 |
| `FUNDED_BY` | 4 |
| `HOLDS_DEBT` | 20 |
| `HOLDS_ROLE_IN` | 7 |
| `LOCATED_IN` | 15 |
| `OWNS_OR_CONTROLS` | 3 |
| `RECEIVES_CONTRACT` | 3 |

## Evidence

- Rows: **221**
- Tier distribution: {'T1': 136, 'T2': 85}
- Review status: {'accepted': 221}
- Edge evidence coverage: **100.0%** (57/57 edges backed by an accepted evidence row)

## Connectivity

- Nodes touched by ≥1 edge: **62**
- Open review-queue items: 0

### Highest-degree nodes (record shows most edge endpoints)

| node_id | degree |
|---------|--------|
| `muni_pr_san_juan` | 15 |
| `entity_3d2fd8a05e1703b2` | 7 |
| `entity_1c1ee3c0f0c85d23` | 6 |
| `entity_125b538f289a4708` | 5 |
| `entity_5204a3d8f84bbfcd` | 4 |
| `entity_6c1d858c1babe390` | 4 |
| `entity_b182f85acf46f69b` | 4 |
| `entity_c5fb8a7f44e8ff18` | 4 |
| `project_puerto_rico_aqueduct_and_sewer_authority_prasa_cip` | 3 |
| `project_puerto_rico_electric_power_authority_prepa_grid_recov` | 3 |
