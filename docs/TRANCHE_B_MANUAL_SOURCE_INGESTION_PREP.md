# Tranche B Manual Source Ingestion Prep

## Active Vector

`PREP_TRANCHE_B_MANUAL_SOURCE_INGESTION`

## Purpose

This document prepares the next implementation tranche after Federation discovery. It defines the manual-source ingestion scope, canonical outputs, schemas, tests, and promotion gates required before any manual source can be marked fully materialized.

This prep document does not ingest, parse, OCR, transform, scrape, or promote source data.

## Scope

| Source Family | Input Class | Priority | Required Output Class |
|---|---|---:|---|
| ACT transition contracts | acquired manual file | P0 | local contract canonical table |
| ACUDEN transition contracts | acquired manual file | P0 | local contract canonical table |
| PRASA completed projects | acquired manual file | P1 | infrastructure project canonical table |
| PRASA FY2024 Consulting Engineer Report | acquired manual file | P1 | infrastructure/fiscal fact tables |
| Puerto Rico cabilderos registry | acquired manual file | P0 | influence-edge canonical table |
| Federal LDA registrants | acquired manual file | P1 | lobbying/client/registrant canonical tables |
| DCAA active contractor listings | acquired manual file | P1 | contractor-reference alias/crosswalk table |

## Required Branch

```text
gpt/manual-source-ingestion-tranche-b
```

## Required Implementation Pattern

Each manual source must follow the same pattern:

1. Define dropzone path.
2. Add parser module under `scripts/`.
3. Add canonical schema under `schemas/`.
4. Add deterministic output path under `data/staging/processed/` or `data/reference/`.
5. Add validation/check function.
6. Add fixture-backed regression tests.
7. Add source-registry or gap-matrix update only after output validation passes.
8. Preserve provenance fields for every parsed row.

## Canonical Output Targets

| Source | Proposed Output | Proposed Schema |
|---|---|---|
| ACT transition contracts | `data/staging/processed/pr_act_transition_contracts.csv` | `schemas/local_contracts.schema.json` |
| ACUDEN transition contracts | `data/staging/processed/pr_acuden_transition.csv` | `schemas/local_contracts.schema.json` |
| PRASA completed projects | `data/staging/processed/prasa_completed_projects.csv` | `schemas/infrastructure_projects.schema.json` |
| PRASA CER | `data/staging/processed/prasa_cer_facts.csv` | `schemas/infrastructure_fiscal_facts.schema.json` |
| PR cabilderos | `data/staging/processed/pr_cabilderos_registry.csv` | `schemas/lobbying_registry.schema.json` |
| Federal LDA registrants | `data/staging/processed/federal_lda_registrants.csv` | `schemas/lobbying_registry.schema.json` |
| DCAA active contractors | `data/staging/processed/dcaa_active_contractors.csv` | `schemas/contractor_reference.schema.json` |

## Minimum Canonical Columns

### Local Contract Outputs

```text
source_id
source_file
record_id
contract_id
contract_title
contractor_name
agency_name
amount
start_date
end_date
fiscal_year
municipality
procurement_type
status
raw_text_excerpt
evidence_tier
confidence
```

### Infrastructure Project Outputs

```text
source_id
source_file
project_id
project_name
asset_type
owner_agency
municipality
status
amount
funding_program
start_date
completion_date
latitude
longitude
raw_text_excerpt
evidence_tier
confidence
```

### Influence Registry Outputs

```text
source_id
source_file
record_id
registrant_name
client_name
person_name
entity_name
relationship_type
registration_date
termination_date
jurisdiction
raw_text_excerpt
evidence_tier
confidence
```

### Contractor Reference Outputs

```text
source_id
source_file
contractor_name
normalized_name
uei
cage
duns
agency_reference
fiscal_year
listing_type
raw_text_excerpt
evidence_tier
confidence
```

## Promotion Gates

| Gate | Requirement |
|---|---|
| Parser gate | Parser reads representative fixture and emits rows |
| Schema gate | Output validates against declared schema |
| Provenance gate | Every row has `source_id`, `source_file`, and evidence/confidence fields |
| Snapshot gate | Regeneration is deterministic |
| Integration gate | Source-registry/gap matrix updated only after schema and tests pass |
| Federation gate | `reports/materialization_readiness.json` updated only after outputs are materialized |

## Test Targets

| Test File | Coverage |
|---|---|
| `tests/test_ingest_act_transition.py` | ACT parser, schema, deterministic output |
| `tests/test_ingest_acuden_transition.py` | ACUDEN parser, amendments/base record handling |
| `tests/test_ingest_prasa.py` | PRASA projects and CER facts |
| `tests/test_ingest_cabilderos.py` | PR cabilderos registry normalization |
| `tests/test_ingest_lda.py` | Federal LDA registrant/client normalization |
| `tests/test_ingest_dcaa_contractors.py` | DCAA contractor alias/crosswalk output |
| `tests/test_manual_ingestion_tranche_b.py` | End-to-end source status and materialization guard |

## Execution Sequence

```text
1. create branch gpt/manual-source-ingestion-tranche-b
2. add shared manual ingestion helpers
3. implement ACT parser and schema
4. implement ACUDEN parser and schema reuse
5. implement PRASA completed-project parser
6. implement PRASA CER fact extractor
7. implement cabilderos parser
8. implement LDA parser
9. implement DCAA active-contractor parser
10. add integration tests and deterministic output checks
11. regenerate source recovery and gap matrices
12. promote only validated sources to materialized status
```

## Stop Conditions

Do not promote a source if any of the following are true:

- parser emits zero rows from a known valid fixture;
- canonical required columns are missing;
- evidence/confidence fields are absent;
- source file provenance is missing;
- generated outputs are nondeterministic;
- test suite fails;
- source status does not reconcile with materialization readiness.

## Next Command

```text
EXECUTE_NEXT_VECTOR: CREATE_BRANCH:gpt/manual-source-ingestion-tranche-b → IMPLEMENT_SHARED_MANUAL_INGESTION_HELPERS → PARSE_ACT_ACUDEN_PRASA_CABILDEROS_LDA_DCAA → VALIDATE_SCHEMAS_AND_TESTS → REGENERATE_READINESS_SURFACES
```
