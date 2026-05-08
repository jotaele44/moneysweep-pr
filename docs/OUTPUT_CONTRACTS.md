# OUTPUT CONTRACTS

## Required Metadata for Every Final Artifact
Every final artifact must include, either in-file or in a paired metadata/status record:
- `production_status`
- `generated_at`
- `schema_version`
- `row_count`
- `source_manifest_hash`
- `source_lineage_coverage`
- `known_gaps`
- `gate_results`
- `forbidden_inputs_used=false`
- `row_fabrication_policy`

## Final Artifact Families
- `contracts_master`
- `financial_flows_master`
- `entities_resolved`
- `alias_registry`
- `execution_chain_master`
- `execution_chain_per_asset`
- `graph_nodes`
- `graph_edges`
- `influence_graph.gexf`
- `asset_control_graph.geojson`
- `risk_alerts_master`
- `complete_output_validation_dashboard`

## Contract Principles
- Output contracts must be versioned and backward-aware.
- Artifact metadata must be deterministic for reproducibility checks.
- Terminal outputs must never be reused as inputs to rebuild master tables.
- Gate outcomes must be attached to outputs so downstream readers can distinguish diagnostic vs production-valid artifacts.
