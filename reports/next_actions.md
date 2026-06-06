# Next Actions

## Current Vector

`CONTRACT_SWEEPER_FEDERATION_READINESS_AUDIT`

This vector adds the Federation control-plane interface for Contract-Sweeper as the future `moneysweep-pr` node. It is metadata/documentation/control-plane only. It does not ingest, parse, OCR, transform, extract, scrape, materialize, or run live producers.

## Completed In This Vector

| Step | Status | Artifact |
|---|---|---|
| Create audit branch | Done | `gpt/federation-readiness-audit` |
| Add Federation manifest | Done | `federation.json` |
| Reconcile 84-source status | Done | `reports/federation_source_status_reconciliation.json` |
| Map Hub callable commands | Done | `docs/FEDERATION_INTERFACE.md` |
| Add readiness audit | Done | `reports/federation_readiness_audit.md` |
| Prep Tranche B manual ingestion | Done | `docs/TRANCHE_B_MANUAL_SOURCE_INGESTION_PREP.md` |

## Current Gate

| Gate | Status |
|---|---|
| Hub discovery | Ready |
| Live Hub execution | Not ready |
| Producer execution | Requires strict preflight |
| Production promotion | Blocked until materialization and validation |

## Next Vector

`PREP_TRANCHE_B_MANUAL_SOURCE_INGESTION → IMPLEMENT_TRANCHE_B_MANUAL_SOURCE_INGESTION`

## Scope

Tranche B covers acquired manual/source files for:

- ACT transition contracts
- ACUDEN transition contracts
- PRASA completed projects
- PRASA FY2024 Consulting Engineer's Report
- Puerto Rico cabilderos registry
- Federal LDA registrants
- DCAA active contractor listings

## Required Tranche B Outputs

Tranche B should create parsers, canonical outputs, schemas, and tests for the acquired files. No source should be marked done or fully materialized until canonical outputs validate and regression tests pass.

## Recommended Branch

`gpt/manual-source-ingestion-tranche-b`

## Execution String

```text
EXECUTE_NEXT_VECTOR: CREATE_BRANCH:gpt/manual-source-ingestion-tranche-b → IMPLEMENT_SHARED_MANUAL_INGESTION_HELPERS → PARSE_ACT_ACUDEN_PRASA_CABILDEROS_LDA_DCAA → VALIDATE_SCHEMAS_AND_TESTS → REGENERATE_READINESS_SURFACES
```
