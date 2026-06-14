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
| Status | Planned; pending registry, importer, schema, tests, and readiness regeneration |

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

## Next Command

```text
EXECUTE_NEXT_VECTOR: CREATE_BRANCH:gpt/sba-recovery-intelligence → ADD_SBA_DISASTER_LOAN_SOURCE_REGISTRY → IMPLEMENT_SBARECOVERYLOAN_SCHEMA → BUILD_NORMALIZER_AND_IMPORTER → ADD_FEMA_COR3_RELATIONSHIPS → VALIDATE_FEDERATION_PROMOTION_RULES
```
