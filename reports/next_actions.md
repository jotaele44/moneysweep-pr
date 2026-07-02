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
| Add canonical SBA recovery source-refresh brief | Done | `docs/SBA_RECOVERY_SOURCE_REFRESH.md` |
| Add text-mode source delta summary | Done | `reports/sba_recovery_source_refresh.txt` |
| Add source registry entry | Done | `registries/source_registry.yaml`, `registries/manual_export_registry.yaml` (+ JSON mirrors) |
| Add importer/schema/tests | Done | `scripts/import_sba_disaster_loans.py`, `schemas/sba_recovery_loan.schema.json`, `tests/test_import_sba_disaster_loans.py` |

## Current Gate

| Gate | Status |
|---|---|
| Hub discovery | Ready |
| Live Hub execution | Not ready |
| Producer execution | Requires strict preflight |
| Production promotion | Blocked until materialization and validation |
| SBA Disaster Loan source promotion | Code/schema/tests complete (0 structural preflight errors); status is `not_materialized` until an operator drops `sba_disaster_loans_pr.xlsx` into `data/manual/sba_disaster_loans/` |

## Next Vector

Pipeline plumbing for `sba_disaster_loans_pr` is complete; materialization now
depends on an operator delivering the source workbook — same class of blocker
as the other manual-export sources in `reports/current_blockers.md` B3. No
automated next vector until a file is dropped.

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

- `SBARecoveryLoan` — done (`schemas/sba_recovery_loan.schema.json`, importer, tests)
- FEMA disaster-number relationships — done, structurally: the `fema_disaster_number` foreign-key field is required and non-null on every emitted record (see `tests/test_import_sba_disaster_loans.py::test_records_carry_relationship_keys`)
- municipality recovery rollups — done (`sba_recovery_loans_pr_municipality_rollup.csv`)
- verified-loss versus approved-loan gap metrics — available per-record via `verified_loss_amount` / `approved_loan_amount`
- COR3 recovery-project comparison hooks — **deferred**, not built. No `COR3RecoveryProject` entity or COR3 data source exists anywhere in this repo; building the comparison would mean inventing a new ingestion pipeline with no real data behind it. See `docs/SBA_RECOVERY_SOURCE_REFRESH.md`.

No source should be marked done or fully materialized until canonical outputs validate and regression tests pass — this remains true; `sba_disaster_loans_pr` stays `not_materialized` until an operator drops the real workbook.
