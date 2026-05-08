# PRODUCTION GATES

## Gate Ladder
- `NON_PRODUCTION_DIAGNOSTIC`
- `PARTIAL_AVAILABLE_SOURCE_COVERAGE`
- `COMPLETE_AVAILABLE_SOURCE_COVERAGE`
- `MVP_VALIDATED`
- `INFRASTRUCTURE_VALIDATED`
- `FINANCIAL_VALIDATED`
- `INFLUENCE_VALIDATED`
- `PRODUCTION_VALIDATED`

## Gate Interpretation
- `NON_PRODUCTION_DIAGNOSTIC`: diagnostic-only outputs; not production valid.
- `PARTIAL_AVAILABLE_SOURCE_COVERAGE`: some required sources represented, gaps remain.
- `COMPLETE_AVAILABLE_SOURCE_COVERAGE`: all available planned sources represented, validation still pending.
- `MVP_VALIDATED`: minimum cross-layer controls pass for constrained production use.
- `INFRASTRUCTURE_VALIDATED`: infrastructure/asset linkage gates pass.
- `FINANCIAL_VALIDATED`: financial-flow and lineage gates pass.
- `INFLUENCE_VALIDATED`: lobbying/political influence link gates pass.
- `PRODUCTION_VALIDATED`: all core production gates pass.

## Implementation Timing
- Documentation/reference patterns can be added now.
- Registry scaffolding after R4.7 merge.
- Production schema/export/lineage implementation after R4.9.
- Graph/risk/report implementation only after R5/R6/R7 pass.

## Blocking Discipline
- Phase 7/8 remains blocked until required upstream gates pass.
- Gate promotion requires evidence in lineage, coverage, resolution, and linkage artifacts.
- Dry-run scaffolding success is not equivalent to source recovery or ingestion completion.
