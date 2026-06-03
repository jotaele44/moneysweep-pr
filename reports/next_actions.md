# Next Actions

## Current Vector

`CONTRACT_SWEEPER_100_PERCENT_COMPLETION_ROADMAP → TRANCHE_A_STATUS_TRUTH`

Tranche A is metadata/control-plane only. It reconciles status truth, readiness counts, source-intake backlog, top-form gap wording, README scope, and next-vector routing. It does not ingest, parse, OCR, transform, extract, materialize, scrape, or run live producers.

## Next Vector

`TRANCHE_B_MANUAL_SOURCE_INGESTION`

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
