CREATE CONSTRAINT prepa_actor_id IF NOT EXISTS
FOR (n:PREPAExportReadyActor)
REQUIRE n.id IS UNIQUE;

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

LOAD CSV WITH HEADERS FROM 'file:///neo4j_edges_export_ready.csv' AS row
MATCH (source:PREPAExportReadyActor {id: row.`:START_ID`})
MERGE (target:PREPAReferenceNode {id: row.`:END_ID`})
MERGE (source)-[r:PREPA_CORRELATION {type: row.`:TYPE`, target_id: row.`:END_ID`}]->(target)
SET
  r.evidence_basis = row.evidence_basis,
  r.confidence = toFloat(row.`confidence:float`),
  r.analytic_label = 'correlation_not_allegation';
