# NORTH STAR PRODUCT SPEC

## Product Definition
Contract-Sweeper is a provenance-first Puerto Rico Public-Money Reconstruction and Infrastructure Control Graph platform that converts public contract, grant, infrastructure, finance, lobbying, political, permit, and asset records into validated master tables, execution chains, GIS-linked assets, graph outputs, probabilistic risk signals, and complete-output validation dashboards.

## Platform Intent
- Produce reproducible, source-traceable master datasets.
- Preserve row-level provenance from ingest to export artifacts.
- Prevent diagnostic outputs from being misrepresented as production-valid results.
- Enforce staged validation before graph, risk, and narrative outputs.

## Core Rules
- No source -> no row.
- No provenance -> no graph edge.
- No confidence score -> no analytical claim.
- No passing gate -> no production report.
- No synthetic rows in production.
- Reports, summaries, graph exports, dashboards, dominance outputs, and risk outputs are terminal products only; they never feed master tables.

## Canonical Pipeline Direction
`INGEST -> NORMALIZE -> RESOLVE -> LINK -> VALIDATE -> EXPORT`

## Provenance and Confidence Requirements
- Every row must carry source system and source-record lineage.
- Every cross-source join must carry confidence scoring.
- Every unresolved or low-confidence high-value entity must go to a review queue.

## Production Discipline
- Diagnostic artifacts must be clearly labeled and separated from production-labeled artifacts.
- Phase 7/8 outputs remain blocked when upstream data-quality and linkage gates fail.
- Completion status is a validation outcome, not a test-count outcome.
