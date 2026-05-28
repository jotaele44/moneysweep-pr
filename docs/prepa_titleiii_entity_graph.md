# PREPA Title III Entity Graph Module

## Purpose

`prepa_titleiii_entity_graph` converts PREPA PROMESA Title III service-matrix entities into a normalized stakeholder graph for downstream procurement and contract correlation.

The module is an enrichment layer and does not infer misconduct.

## Source Type

Primary source:
- Federal court procedural records
- PROMESA Title III service matrices
- PREPA restructuring notices

Evidence classification:
- T1 technical / primary

## Functional Flow

```text
service_matrix.csv
    ↓
entity extraction
    ↓
name normalization
    ↓
sector classification
    ↓
stakeholder graph generation
    ↓
contract/procurement correlation
    ↓
confidence + evidence scoring
    ↓
JSON export
```

## Sector Taxonomy

| Sector | Description |
|---|---|
| legal | law firms / counsel |
| finance_bondholder | lenders / banks / funds |
| energy_fuel | LNG / fuel / generation |
| infrastructure_contractor | engineering / construction |
| government_public_authority | agencies / authorities |
| labor_pension | unions / pension systems |
| individual | natural persons |
| unknown | unresolved |

## Supported Correlation Flags

| Flag | Meaning |
|---|---|
| PREPA_STAKEHOLDER_OVERLAP | general overlap |
| COUNSEL_COUNTERPARTY_OVERLAP | legal representation overlap |
| FUEL_RESTRUCTURING_OVERLAP | fuel + restructuring overlap |
| GRID_PRIVATIZATION_OVERLAP | contractor + grid transition overlap |
| FINANCIAL_CLAIMANT_OVERLAP | finance actor overlap |
| PUBLIC_AUTHORITY_INTERLOCK | public authority overlap |

## Example Usage

```python
from contract_sweeper.modules.prepa_titleiii_entity_graph import run

run(
    service_matrix_csv="data/prepa/service_matrix.csv",
    output_json="outputs/prepa_graph.json",
)
```

## Important Constraints

- Correlation is not causation.
- Stakeholder appearance in Title III records is not evidence of misconduct.
- Investigative escalation requires multi-source corroboration.
- Confidence scoring is probabilistic.
- Exact-name matching alone is insufficient for attribution.

## Recommended Downstream Datasets

- FPDS
- USASpending
- FSRS
- PREPA fuel procurement
- LUMA Energy transition records
- Genera PR operational records
- AAFAF disclosures
- FOMB fiscal plans
- litigation dockets

## Planned Expansion

- Neo4j graph export
- fuzzy alias resolution
- temporal clustering
- procurement anomaly scoring
- infrastructure dependency mapping
- LNG/fuel network visualization
