# PR4 Influence Graph Builder — Delta Report

**Branch:** `claude/r5-pr4-influence-graph`
**Date:** 2026-05-12

## Results

| Metric | Value |
|---|---|
| node_count | 117,178 |
| edge_count | 854,916 |
| graphml_written | true |
| gexf_written | true |
| top_25_written | true |

## Top 5 Control Entities by Contract Value Weight

| Rank | Node | Type | Contract Value Weight ($) |
|---|---|---|---|
| 1 | Department of Health and Human Services | agency | 147,505,525,097 |
| 2 | MULTIPLE RECIPIENTS | prime (aggregate) | 91,997,224,445 |
| 3 | Department of Homeland Security | agency | 67,715,237,744 |
| 4 | Department of Agriculture | agency | 49,971,611,383 |
| 5 | (see top_25_control_entities.csv) | … | … |

Note: "MULTIPLE RECIPIENTS" is the aggregate/unknown-recipient placeholder used by USAspending when the actual subrecipient is not disclosed. It is not a real entity.

## Edge types

| Type | Meaning |
|---|---|
| `awards_to` | Agency → prime (from awards master) |
| `parent_of` | Parent entity → subsidiary (from parent_uei field) |
| `located_in` | Prime/sub/asset → municipality |
| `subawards_to` | Prime → subcontractor (from execution chains) |
| `executes_project` | Sub → project/asset |
| `lobbies_for` | LDA registrant → client |
| `contributes_to` | Donor → campaign committee (FEC) |
| `underwrites` | Bond dealer → issuer (EMMA) |

## Outputs

- `data/staging/processed/graphs/entity_nodes.csv` — 117,178 rows
- `data/staging/processed/graphs/entity_edges.csv` — 854,916 rows
- `data/staging/processed/graphs/graph_metrics.csv` — 117,178 rows
- `data/staging/processed/graphs/top_25_control_entities.csv` — 25 rows
- `data/staging/processed/graphs/influence_graph.graphml`
- `data/staging/processed/graphs/influence_graph.gexf`

## Next

PR5: Gap analysis + `gap_analysis_report.csv` + cleanup of stale r4_X review queue artifacts.
