# moneysweep-pr Top-Form Development Checklist

## Purpose

This document defines the production-complete target state for moneysweep-pr.

A top-form moneysweep-pr installation must ingest, normalize, validate, resolve, score, and export Puerto Rico public-money datasets across federal procurement, territorial contracts, municipal contracts, infrastructure, lobbying, campaign finance, debt, grants, public records, contractor-reference registries, and geospatial layers.

This document is a control artifact. It defines completion gates. It does not claim that the repository is currently production-complete.

## Status Vocabulary

Use the following status values in top-form tracking artifacts:

- `done`: requirement is implemented, tested, and reproducible.
- `partial`: requirement is implemented in part, but not complete or not fully validated.
- `missing`: requirement is not implemented.
- `blocked`: requirement cannot advance because of an unresolved external or internal blocker.
- `manual_required`: requirement depends on a manual export, manual download, or human-provided input.
- `auth_required`: requirement depends on credentials, an API key, or authorized access.
- `unknown`: current state is not yet verified.

Do not introduce synonym statuses without updating the schema and validator.

These top-form statuses are development-tracking statuses and do not replace source materialization statuses such as `fully_materialized`, `partially_materialized`, `not_materialized`, `below_threshold`, or `no_outputs_declared`.

## Evidence Tiers

- `T1`: technical or official machine-readable source, such as API output, registry export, structured CSV, official database record, or signed source document.
- `T2`: operational source, agency report, formal filing, public registry page, procurement document, audit report, financial report, court record, or official PDF.
- `T3`: eyewitness, operator-provided, or human-provided source requiring corroboration.
- `T4`: secondary, derivative, journalistic, analytical, or non-primary source.

All graph and influence outputs should carry evidence tier and confidence metadata.

## Production Gates

### Gate 1: Source Registry Lock

- [ ] Every source has a stable `source_id`.
- [ ] Every source has explicit `required` status.
- [ ] Every source has explicit `intake_mode`.
- [ ] Every source has explicit `materialization_status`.
- [ ] Every source has declared output paths.
- [ ] Every source has blocker status or blocker class.
- [ ] Every source has refresh cadence.
- [ ] Every required source has a validation rule.
- [ ] Materialization vocabulary is stable.
- [ ] Status vocabulary is not duplicated with near-synonyms.

### Gate 2: Required Source Materialization

- [ ] `usaspending_prime`
- [ ] `fsrs_subawards`
- [ ] `sam_entities`
- [ ] `cor3`
- [ ] `hud_drgr_authorized`
- [ ] `prasa`
- [ ] `oficina_contralor`
- [ ] `emma_bonds`
- [ ] `pr_cabilderos`

A required source may be accepted as temporarily unresolved only if it is explicitly classified as `blocked`, `manual_required`, or `auth_required`, with a documented next action.

### Gate 3: Federal Procurement Spine

- [ ] FPDS ingestion.
- [ ] USASpending ingestion.
- [ ] FSRS ingestion.
- [ ] SAM enrichment.
- [ ] Deduplicated procurement master.
- [ ] Coverage matrix.
- [ ] Vendor dominance report.
- [ ] Single-source or noncompetitive award flags.
- [ ] Agency concentration metrics.
- [ ] Fiscal-year trend report.

### Gate 4: Puerto Rico Local Contract Intake

- [ ] ACT transition contracts.
- [ ] ACUDEN transition contracts.
- [ ] PRASA completed projects.
- [ ] PRASA FY2024 Consulting Engineer's Report.
- [ ] COR3 recovery records.
- [ ] Oficina del Contralor contract records.
- [ ] PREPA contracts.
- [ ] P3 / APP contracts.
- [ ] Municipal procurement records.
- [ ] Contract amendment linkage.

Base contracts and amendments must remain linkable. Analytical rollups may collapse amendment chains, but raw canonical rows should preserve parent-child relationships.

### Gate 5: Entity Master

- [ ] Entity master.
- [ ] Alias table.
- [ ] Parent/subsidiary map.
- [ ] Person master.
- [ ] Agency master.
- [ ] Municipality master.
- [ ] Review queue.
- [ ] Confidence scoring.
- [ ] Stable entity IDs.
- [ ] Entity-resolution regression tests.

Stable entity IDs should be preserved across runs unless a deliberate migration is documented.

### Gate 6: Influence Layer

- [ ] Puerto Rico cabilderos registry.
- [ ] Federal LDA records.
- [ ] Campaign finance records.
- [ ] Contractor-donor overlap.
- [ ] Lobbyist-person mapping.
- [ ] Client-entity mapping.
- [ ] Time-bounded influence windows.
- [ ] Influence confidence scoring.
- [ ] Influence graph edges.
- [ ] Influence report.

Influence records must not be treated as proof of improper conduct. They are structural signals requiring context, source traceability, and confidence scoring.

### Gate 7: Debt / Fiscal Control Layer

- [ ] EMMA / MSRB bond records.
- [ ] Issuer registry.
- [ ] Debt instrument table.
- [ ] Creditor groups.
- [ ] Fiscal control events.
- [ ] Restructuring milestones.
- [ ] Legal, financial, and advisory entities.
- [ ] Debt-to-contract overlap.
- [ ] Debt graph exports.
- [ ] Debt/fiscal control report.

### Gate 8: GIS / Infrastructure Layer

- [ ] 78-municipio crosswalk.
- [ ] Municipality aliases.
- [ ] Geo resolution reason codes.
- [ ] Project geocoding.
- [ ] Infrastructure asset registry.
- [ ] Infrastructure sector tags.
- [ ] GeoJSON exports.
- [ ] Temporal infrastructure layer.
- [ ] Headquarters-bias correction.
- [ ] GIS layer manifest.

Geographic outputs must distinguish vendor headquarters from place of performance, project location, asset location, and municipality of benefit.

### Gate 9: Graph Export

- [ ] Node schema.
- [ ] Edge schema.
- [ ] Neo4j CSV export.
- [ ] GraphML export.
- [ ] Evidence tier per edge.
- [ ] Confidence per edge.
- [ ] Provenance per edge.
- [ ] Temporal validity fields.
- [ ] Deduplicated node IDs.
- [ ] Graph QA report.

### Gate 10: Analyst Product

- [ ] Top entities report.
- [ ] Top contract clusters report.
- [ ] Top influence clusters report.
- [ ] Municipality density report.
- [ ] FOIA / public-records priority queue.
- [ ] Dashboard or static explorer.
- [ ] Source drilldown.
- [ ] Layer toggles.
- [ ] Exportable briefing packet.
- [ ] Reproducibility guide.

### Gate 11: Test / CI / Reproducibility

- [ ] Unit tests.
- [ ] Integration tests.
- [ ] Adapter smoke tests.
- [ ] Fixture datasets.
- [ ] Output schema snapshot tests.
- [ ] Entity-resolution tests.
- [ ] Graph export tests.
- [ ] GIS export tests.
- [ ] Strict preflight.
- [ ] Fresh clone reproduction.

## Production Complete Definition

moneysweep-pr is production-complete only when:

1. Required sources are materialized or explicitly classified as blocked, manual-required, or auth-required.
2. All required source schemas validate.
3. Master procurement, local-contract, influence, entity, debt, graph, and GIS tables build reproducibly.
4. Entity IDs are stable across runs.
5. Evidence tier and confidence fields exist on all graph and influence edges.
6. Graph and GIS exports pass QA.
7. Analyst reports regenerate without manual editing.
8. The full test suite passes.
9. Strict preflight passes for structural checks.
10. Current status, blockers, and next actions are synchronized.
