# PREPA Export-Ready Graph Load Recipe

## Scope

This recipe loads only the manually reviewed PREPA export-ready registry.

Source registry:

    outputs/prepa_full_universe/postmatch_qa_strict/prepa_export_ready_registry.csv

Export package:

    outputs/prepa_full_universe/export_ready_graph/

## Load-Ready Artifacts

| Artifact | Purpose |
|---|---|
| neo4j_nodes_export_ready.csv | Neo4j node import |
| neo4j_edges_export_ready.csv | Neo4j edge import |
| gis_entities_export_ready.csv | GIS entity layer |
| prepa_export_ready.graphml | GraphML import / interchange |
| artifact_manifest.json | manifest and scope constraint |

## Validation Status

Latest validation report:

    reports/prepa_export_ready_graph_validation.json

Expected validation values:

    validation_status = PASS
    graphml_status = parse_ok
    dangling_edge_count = 0

## Neo4j CSV Import

Copy files into Neo4j import directory:

    cp outputs/prepa_full_universe/export_ready_graph/neo4j_nodes_export_ready.csv "$NEO4J_HOME/import/"
    cp outputs/prepa_full_universe/export_ready_graph/neo4j_edges_export_ready.csv "$NEO4J_HOME/import/"

Create constraint:

    CREATE CONSTRAINT prepa_actor_id IF NOT EXISTS
    FOR (n:PREPAExportReadyActor)
    REQUIRE n.id IS UNIQUE;

Load nodes:

    LOAD CSV WITH HEADERS FROM 'file:///neo4j_nodes_export_ready.csv' AS row
    MERGE (n:PREPAExportReadyActor {id: row.`id:ID`})
    SET
      n.canonical_name = row.canonical_name,
      n.sector = row.sector,
      n.continuity_score = toFloat(row.`continuity_score:float`),
      n.temporal_edges = toInteger(row.`temporal_edges:int`),
      n.dataset_count = toInteger(row.`dataset_count:int`),
      n.export_status = row.export_status,
      n.manual_review_reason = row.manual_review_reason,
      n.analytic_label = row.analytic_label;

Load relationships:

    LOAD CSV WITH HEADERS FROM 'file:///neo4j_edges_export_ready.csv' AS row
    MATCH (source:PREPAExportReadyActor {id: row.`:START_ID`})
    MERGE (target:PREPAReferenceNode {id: row.`:END_ID`})
    MERGE (source)-[r:PREPA_CORRELATION {type: row.`:TYPE`, target_id: row.`:END_ID`}]->(target)
    SET
      r.evidence_basis = row.evidence_basis,
      r.confidence = toFloat(row.`confidence:float`),
      r.analytic_label = 'correlation_not_allegation';

## GIS Import

Use:

    outputs/prepa_full_universe/export_ready_graph/gis_entities_export_ready.csv

GIS handling:

- Treat as a non-geocoded entity layer.
- Do not infer facility locations from service addresses.
- Join later to project/facility datasets using canonical entity names or contract IDs.
- Keep geocode_status = not_geocoded until address-level confirmation.

## Analytic Constraint

This graph encodes correlation and continuity signals only.

It does not encode fraud, corruption, collusion, causation, or illegal coordination.
