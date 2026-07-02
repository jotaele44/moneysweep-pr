# SBA Recovery Source Refresh

## Active Vector

`MONEYSWEEP_SBA_RECOVERY_INTELLIGENCE`

## New Source

| Field | Value |
|---|---|
| Source ID | `sba_disaster_loans_pr` |
| Name | SBA Disaster Loan Data - Puerto Rico |
| Owner | U.S. Small Business Administration |
| Input | `sba_disaster_loans_pr.xlsx` |
| Sheets | `FY22 Home`, `FY22 Business` |
| Status | Registry, importer, schema, tests, and readiness regeneration complete. `not_materialized` until an operator drops `sba_disaster_loans_pr.xlsx` into `data/manual/sba_disaster_loans/`. |

## MoneySweep Coverage Added

- disaster recovery assistance
- federal recovery funding
- verified loss analysis
- approved loan distribution
- municipality recovery rollups
- FEMA disaster-number correlation
- COR3 recovery-project comparison hooks

## Required Entity

```text
SBARecoveryLoan
```

## Required Files To Implement Next

```text
schemas/sba_recovery_loan.schema.json
scripts/import_sba_disaster_loans.py
tests/test_import_sba_disaster_loans.py
reports/sba_recovery_import_summary.md
```

## Required Registry Updates

```text
registries/source_registry.yaml
registries/source_registry.json
reports/materialization_readiness.json
reports/source_registry_status.csv
```

Do not update readiness counts as materialized until the parser, schema, lineage, row-count, relationship-key, and regression gates pass.

## Required Relationships

```text
SBARecoveryLoan REFERENCES_FEMA_DISASTER FEMARecoveryEvent
SBARecoveryLoan ROLLS_UP_TO_MUNICIPALITY Municipality
MunicipalityRecoveryRollup COMPARES_WITH_COR3_PROJECTS COR3RecoveryProject
```

`REFERENCES_FEMA_DISASTER` and `ROLLS_UP_TO_MUNICIPALITY` are implemented
structurally: every `SBARecoveryLoan` record carries a required, non-null
`fema_disaster_number` and `municipality` foreign-key field (enforced by
`tests/test_import_sba_disaster_loans.py::test_records_carry_relationship_keys`).
This matches the repo's existing convention for cross-source references —
no other source in this repo (e.g. `pr_prime_sub_relationships.csv`,
`pr_gleif_relationships.csv`) builds a separate graph-edge table for FK-style
relationships either.

`COMPARES_WITH_COR3_PROJECTS` is **deliberately deferred, not implemented**.
Neither `COR3RecoveryProject` nor `FEMARecoveryEvent` exists anywhere in this
codebase as a real entity, schema, or data source — there is no COR3
ingestion pipeline to join against. Building this relationship would mean
inventing an entirely new source from scratch with no real data behind it,
which is out of scope for materializing `sba_disaster_loans_pr`. Revisit if
and when a COR3 recovery-project source is actually registered.

## Status

Registry entries, `SBARecoveryLoan` schema, importer (including the
municipality rollup output), and tests are complete —
`tests/test_import_sba_disaster_loans.py` covers header-row detection,
column normalization, schema conformance, and relationship-key presence
end-to-end against a synthetic fixture workbook. `python3 run_all.py
--only-setup --strict-preflight` reports 0 structural errors with this
source registered. Remaining step: an operator must drop the real
`sba_disaster_loans_pr.xlsx` into `data/manual/sba_disaster_loans/` before
`reports/source_registry_status.csv` will show this source as materialized.
