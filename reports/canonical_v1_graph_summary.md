# Canonical v1 Graph Summary

**Gate:** `NON_PRODUCTION_DIAGNOSTIC` · **Generated:** 2026-06-01T12:53:12.341125+00:00

_Descriptive, derived summary of the committed canonical_v1 tables. Asserts no new sourced claims; every figure is a count over existing, evidence-backed rows. Phrasing follows `docs/CLAIM_LANGUAGE_POLICY.md`._

## Nodes (187 total)

| Table | Count |
|-------|-------|
| `people` | 60 |
| `entities` | 22 |
| `roles` | 7 |
| `contracts` | 0 |
| `projects` | 0 |
| `debt_instruments` | 20 |
| `lobbying_records` | 0 |
| `funding_sources` | 0 |
| `properties` | 0 |
| `municipalities` | 78 |

## Edges (42 total)

| edge_type | Count |
|-----------|-------|
| `ADVISES` | 5 |
| `HOLDS_DEBT` | 20 |
| `HOLDS_ROLE_IN` | 7 |
| `LOCATED_IN` | 10 |

## Evidence

- Rows: **202**
- Tier distribution: {'T1': 136, 'T2': 66}
- Review status: {'accepted': 202}
- Edge evidence coverage: **100.0%** (42/42 edges backed by an accepted evidence row)

## Connectivity

- Nodes touched by ≥1 edge: **47**
- Open review-queue items: 0

### Highest-degree nodes (record shows most edge endpoints)

| node_id | degree |
|---------|--------|
| `muni_pr_san_juan` | 10 |
| `entity_3d2fd8a05e1703b2` | 7 |
| `entity_1c1ee3c0f0c85d23` | 6 |
| `entity_125b538f289a4708` | 5 |
| `entity_5204a3d8f84bbfcd` | 4 |
| `entity_6c1d858c1babe390` | 4 |
| `entity_b182f85acf46f69b` | 4 |
| `entity_c5fb8a7f44e8ff18` | 4 |
| `entity_d363e4ddf2ce6a5d` | 2 |
| `debt_commonwealth_of_puerto_rico_go_2012_745145sk7` | 1 |
