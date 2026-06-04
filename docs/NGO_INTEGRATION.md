# NGO / OSFL Integration Layer

## Active Vector

`NGO_INTEGRATION_ISLANDWIDE_COVERAGE`

This layer extends Contract-Sweeper beyond procurement vendors by adding a first-class NGO / OSFL execution-chain layer. The goal is to track nonprofit identity, award exposure, municipal coverage, and graph relationships without mutating the existing FPDS / USASpending / FSRS pipeline.

## Execution Command

```bash
python3 scripts/ngo_integration.py
```

Schema-only mode:

```bash
python3 scripts/ngo_integration.py --schema-only
```

Targeted tests:

```bash
python3 -m pytest tests/test_ngo_integration.py -v
```

## Input Layout

The script creates the needed directories if they do not exist. Drop source files here:

```text
data/raw/ngos/irs_eo_bmf/*.csv
data/raw/ngos/irs_eo_bmf/*.txt
data/raw/ngos/teos/*.csv
data/raw/ngos/teos/*.json
data/raw/ngos/teos/*.jsonl
data/raw/ngos/pr_state_registry/*.csv
data/raw/ngos/usaspending/*.csv
data/raw/ngos/usaspending/*.json
data/raw/ngos/usaspending/*.jsonl
```

It also reads existing processed Contract-Sweeper award outputs when present:

```text
data/staging/processed/pr_contracts_master.csv
data/staging/processed/master_enriched.csv
```

## Primary Outputs

```text
data/staging/processed/ngos/ngos_master.csv
data/staging/processed/ngos/ngo_alias_registry.json
data/staging/processed/ngos/ngo_funding_edges.csv
data/staging/processed/ngos/ngo_municipal_coverage.csv
data/staging/processed/ngos/ngo_review_queue.csv
data/staging/processed/ngos/ngo_duplicate_candidates.csv
data/staging/processed/ngos/ngo_disaster_recovery_exposure.csv
data/staging/processed/ngos/ngo_asset_edges.csv
data/staging/processed/ngos/ngo_fiscal_sponsor_edges.csv
data/staging/processed/ngos/ngo_graph.gexf
data/staging/processed/ngos/ngo_coverage_report.md
data/staging/processed/ngos/ngo_validation_report.json
```

Schema files:

```text
data/staging/processed/ngos/schema/ngos_master.schema.json
data/staging/processed/ngos/schema/ngo_funding_edges.schema.json
data/staging/processed/ngos/schema/ngo_municipal_coverage.schema.json
data/staging/processed/ngos/schema/ngo_asset_edges.schema.json
data/staging/processed/ngos/schema/ngo_fiscal_sponsor_edges.schema.json
```

Tabular outputs are additionally written as Parquet (with automatic CSV fallback
when `pyarrow` is unavailable), e.g. `ngos_master.parquet`,
`ngo_funding_edges.parquet`, `ngo_asset_edges.parquet`,
`ngo_fiscal_sponsor_edges.parquet`, `ngo_municipal_coverage.parquet`.

## Coverage Logic

The script always generates a 78-municipality coverage matrix. A municipality can be marked as:

- `covered`
- `registered_ngos_no_funding_edge_yet`
- `funding_detected_but_no_registry_match`
- `no_registered_or_funded_ngo_detected`

Coverage is therefore not silently assumed. Missing or weakly supported municipalities remain explicit review targets.

## Current Confidence Model

`ngos_master.csv` confidence is based on available identity fields:

| Evidence | Current Weight |
|---|---:|
| EIN | +30 |
| UEI | +20 |
| PR corporate ID | +20 |
| IRS status present and not `unknown` | +10 |
| PR status present and not `unknown` | +10 |
| Municipality detected | +10 |
| Legal name present | +10 |
| Canonical IRS source (EO BMF / TEOS) | +15 |
| Canonical PR state registry source | +10 |

Current bands:

| Score | Review Status |
|---:|---|
| 90-100 | `confirmed` |
| 75-89 | `strong_probable` |
| 60-74 | `probable` |
| 40-59 | `needs_review` |
| <40 | `lead_only` |

An explicit **canonical-source bonus** lifts rows backed by authoritative
provenance: IRS EO BMF / TEOS rows receive +15 and PR state-registry rows +10. As
a result, an IRS EO BMF-only record with EIN + IRS active + municipality + legal
name now scores ~75 (`strong_probable`) rather than the previously conservative
~60, while rows backed only by weaker sources are unaffected.

## Entity Resolution Rules Implemented

1. Exact EIN deduplicates automatically.
2. If no EIN exists, records merge on normalized legal name + municipality.
3. Source IDs are retained and merged.
4. Alias names are retained as JSON.
5. Fiscal sponsorship is reserved as an edge file and is not collapsed into NGO identity.

## Award Join Logic Implemented

The script checks existing processed award files and raw NGO USASpending drops. It attempts matches by:

1. Recipient EIN, when present.
2. Exact normalized recipient name.
3. NGO-like name heuristic for lead-only recipient detection.

Award-like fields are normalized into `ngo_funding_edges.csv`.

## Graph Layer

`ngo_graph.gexf` exports:

- NGO nodes
- Municipality nodes
- Funder / agency nodes
- `located_in` edges
- funding / recipient edges

This is intentionally generic GEXF so it can be opened in Gephi or merged later into `influence_graph.gexf`.

## Validation Gates

Minimum current gates:

| Gate | Status |
|---|---|
| Schema files generated | Implemented |
| 78-municipality matrix | Implemented |
| NGO identity table | Implemented |
| Funding edge table | Implemented |
| Alias registry | Implemented |
| Review queue | Implemented |
| Duplicate queue | Implemented |
| Disaster-recovery exposure extract | Implemented |
| GEXF graph export | Implemented |
| Asset edges | Implemented |
| Fiscal sponsor edges | Implemented |
| Parquet exports | Implemented |
| README integration | Implemented |
| Influence-graph merge | Implemented |
| Live source downloaders | Deferred (layer runs on dropped-in files; bulk IRS/TEOS/PR-registry downloaders are a separate manual-export concern) |

## Asset Edges

`ngo_asset_edges.csv` links funded NGOs to infrastructure assets/projects. An NGO
is asset-linked when one of its funding edges resolves to a known asset/project id
found in the award sources, the execution-chain master, or the FEMA PA master —
either by award id (`evidence_class=award_id_match`, confidence 80) or by
normalized recipient name + municipality (`evidence_class=name_muni_match`,
confidence 55). The 78-municipality matrix's `ngo_count_asset_linked` is populated
from these edges.

## Fiscal Sponsor Edges

`ngo_fiscal_sponsor_edges.csv` captures umbrella relationships from two signals:

1. **Declared overrides** — a `fiscal_sponsor` / `sponsored_by` column on a
   dropped-in row (`relationship_type=declared_fiscal_sponsor`, confidence 80).
2. **IRS group exemptions** — organizations sharing a Group Exemption Number (GEN)
   form a group ruling; the central organization (affiliation code 6) is emitted
   as the sponsor of its subordinates (affiliation code 9)
   (`relationship_type=group_exemption`, confidence 70).

## Recommended Next Vector

```text
EXECUTE_NEXT_VECTOR: STAGE_IRS_TEOS_PR_REGISTRY_BULK_DROPS → BACKFILL_GROUP_EXEMPTION_AND_AFFILIATION_FIELDS → REVIEW_ASSET_EDGE_NAME_MATCHES
```
