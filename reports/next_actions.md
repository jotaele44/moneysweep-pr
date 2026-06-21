# Next Actions

## Current Vector

`PREP_TRANCHE_B_MANUAL_SOURCE_INGESTION`

This vector prepares the control plane for Tranche B manual source ingestion. The prior source-count reconciliation (84→136) and SBA disaster-loan documentation are both complete. This is the current active development vector.

## Completed In Prior Federation Vector

| Step | Status | Artifact |
|---|---|---|
| Create audit branch | Done | `gpt/federation-readiness-audit` |
| Add Federation manifest | Done | `federation.json` |
| Reconcile 84-source status | Done | `reports/federation_source_status_reconciliation.json` |
| Reconcile 136-source status (source-count wording) | Done | `federation.json`, `reports/federation_source_status_reconciliation.json`, `docs/FEDERATION_INTERFACE.md`, `README.md`, `reports/federation_readiness_audit.md`, `reports/current_status.json` |
| Map Hub callable commands | Done | `docs/FEDERATION_INTERFACE.md` |
| Add readiness audit | Done | `reports/federation_readiness_audit.md` |
| Prep Tranche B manual ingestion | Done | `docs/TRANCHE_B_MANUAL_SOURCE_INGESTION_PREP.md` |

## Completed In This Source-Refresh Vector

| Step | Status | Artifact |
|---|---|---|
| Add SBA Disaster Loan source to documentation surface | Done | `README.md` |
| Add canonical SBA recovery source-refresh brief | Pending | `docs/SBA_RECOVERY_SOURCE_REFRESH.md` |
| Add text-mode source delta summary | Pending | `reports/sba_recovery_source_refresh.txt` |
| Add source registry entry | Pending implementation | `registries/source_registry.yaml` / `registries/source_registry.json` |
| Add importer/schema/tests | Pending implementation | `scripts/`, `schemas/`, `tests/` |

## Current Gate

| Gate | Status |
|---|---|
| Hub discovery | Ready |
| Live Hub execution | Not ready |
| Producer execution | Requires strict preflight |
| Production promotion | Blocked until materialization and validation |
| SBA Disaster Loan source promotion | Blocked until parser, schema, lineage, and tests pass |

## Next Vector

`SBA_RECOVERY_SOURCE_REGISTRY_AND_IMPORTER → IMPLEMENT_SBA_DISASTER_LOAN_INGESTION`

## Scope

Tranche B covers acquired manual/source files for:

- ACT transition contracts
- ACUDEN transition contracts
- PRASA completed projects
- PRASA FY2024 Consulting Engineer's Report
- Puerto Rico cabilderos registry
- Federal LDA registrants
- DCAA active contractor listings
- SBA Disaster Loan Puerto Rico workbook: FY22 Home and FY22 Business sheets

## Required SBA Recovery Outputs

SBA recovery ingestion should create parser, canonical output, schema, tests, and relationship docs for:

- `SBARecoveryLoan`
- FEMA disaster-number relationships
- municipality recovery rollups
- verified-loss versus approved-loan gap metrics
- COR3 recovery-project comparison hooks

No source should be marked done or fully materialized until canonical outputs validate and regression tests pass.

## Recommended Branch

`gpt/sba-recovery-intelligence`

## Execution String

```text
EXECUTE_NEXT_VECTOR: CREATE_BRANCH:gpt/sba-recovery-intelligence → ADD_SBA_DISASTER_LOAN_SOURCE_REGISTRY → IMPLEMENT_SBARECOVERYLOAN_SCHEMA → BUILD_NORMALIZER_AND_IMPORTER → ADD_FEMA_COR3_RELATIONSHIPS → VALIDATE_FEDERATION_PROMOTION_RULES
```
