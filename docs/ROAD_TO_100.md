# Road to 100 — normalized federation score

**Metadata refresh:** 2026-08-19 at `57cd18e4e8fba55160dcba42a5146dcf914c14e7`
**Evidence audit date:** 2026-08-04 (not recertified by the metadata refresh)
**Scoring model:** code completeness 20%; main-branch availability 15%; CI enforcement 15%; data materialization 15%; operator verification 15%; GUI completeness 10%; federation readiness 10%.

## Current normalized score: 61.70 / 100

| Dimension | Weight | Score | Weighted |
|---|---:|---:|---:|
| Code completeness | 20 | 78 | 15.60 |
| Main-branch availability | 15 | 72 | 10.80 |
| CI enforcement | 15 | 82 | 12.30 |
| Data materialization | 15 | 45 | 6.75 |
| Operator verification | 15 | 35 | 5.25 |
| GUI completeness | 10 | 70 | 7.00 |
| Federation readiness | 10 | 40 | 4.00 |

This repository remains `NON_PRODUCTION_DIAGNOSTIC`. The normalized score does not award production credit for registered sources, schemas or resumable producers until source bytes, lineage and operator receipts exist.

## State reconciliation

- The Wave 0 architecture, source registry, ingestion framework, desktop/frontend improvements and release guard are substantially implemented.
- Required sources remain incomplete: COR3, HUD DRGR, cabilderos and PRASA.
- PR #453 merged; its code is present, while OCPR materialization and completeness gates remain unresolved.
- Isolated setup no longer depends on a sibling checkout: requirements pin the shared package to an immutable Git source. This does not certify live-source execution.
- PR #458 is a release-safety guard and should land before any desktop tag can be considered.
- PR #459 is rescued audit/staging state, not certified production data.
- FEC Schedule E and related reconciliation remain operator-run work.
- Entity-master lineage, source freshness and external-universe completeness remain unresolved.

## Priority exit sequence

1. Materialize the four required source exports with exact receipts.
2. Complete OCPR O&M materialization and 78-municipality/public-corporation accounting.
3. Complete FEC Schedule E/B reconciliation and preserve unresolved-row evidence.
4. Resolve entity-master lineage and rerun the 151-source audit.
5. Adjudicate rescued PR #459 without promoting deletions or outputs by assumption.
6. Land release and isolation guards.
7. Recompute production status only after real-data R5 gates and downstream federation validation pass.

## Machine-readable authority

See `docs/unfinished_implementation_ledger.v1.json`. New analytical verticals do not outrank required-source closure.

## PR #452 post-merge reconciliation evidence

The normalized score above is the current federation-wide authority (audit 2026-08-04). The sections below preserve the PR #452 reconciliation evidence for the Wave 0 entity-product and lineage adjudication without opening production status.

## Certified baseline

| Control | Result |
|---|---:|
| Registry sources | 151 |
| Automatable / structurally ready | 104 / 104 |
| Queued or excluded | 47 |
| Fully / partially / not materialized | 67 / 11 / 73 |
| Required fully materialized | 10 / 14 |
| Registry source-ID digest | `7830358c254767bc9db34ae5230b41f815ffaea9aa0c3abe4dfdebfe36b2f2d0` |
| Physical processed rows | 1,183,565 |
| Registry-declared rows | 849,898 |
| Adjudicated derived rows | 212,930 |
| Pipeline intermediates | 120,737 |
| Unadjudicated orphan rows | 0 |
| Derived rows with unresolved lineage | 0 |
| Live universe probe | Not run |

The complete 151-source audit was not rerun because the supplied upload set is only a partial corpus. Baseline source counts remain certified and unchanged.

## Required-export upload adjudication

| Source | Supplied evidence | Result |
|---|---|---|
| `cor3` | `pr_cor3_projects.csv` | Header-only, 0 rows; no credit |
| `hud_drgr_authorized` | Two HUD DRGR Parquets | Both 0 rows and not registry staging CSVs; no credit |
| `pr_cabilderos` | `pr_cabilderos.csv` | Header-only, 0 rows; no credit |
| `prasa` | `pr_prasa_contracts(1).csv` | Header-only, 0 rows; no credit |

`pr_hud_hcv.csv` is a Housing Choice Voucher summary, not a DRGR export. Federal awards mentioning PRASA and PREPA contract records are not substitutes for an official PRASA contract export.

Evidence is recorded in `reports/WAVE0_REQUIRED_EXPORT_INGESTION_RECEIPT_2026-07-30.json`.

## Entity-product comparison

The uploaded `entity_master(2).csv` contains 104,280 valid rows. The uploaded 453,352-row awards master reproducibly generated a 104,280-row entity-profile spine using the `analyze_entity_profiles.py` normalization and aggregation contract.

A comparator defect was corrected: staging `entity_master.csv` uses `entity_key`, but `entity_key` was absent from the stable-key candidate list. With the proper keys:

- left stable key: `entity_key`;
- right stable key: `normalized_name`;
- unique keys: 104,280 on each side;
- intersection: 104,280;
- stable-key overlap and Jaccard: 100%;
- shared `award_count` and `fiscal_year_range` row projection: 100%;
- classification: `OVERLAPPING_DERIVED_PRODUCTS`;
- not byte-identical and not semantic duplicates because the schemas serve different purposes.

The actual enriched `pr_entity_profiles.csv` and its 990, CMS, and FDIC supplementary inputs were not supplied, so the comparison is certified for the common awards spine rather than every enrichment column.

## Lineage resolution

`data/staging/processed/entity_master.csv` is produced by `scripts/build_unified_master.py`, not `scripts/build_entity_master.py`. The uploaded artifact matches the reconstructed awards aggregation on all 104,280 entity keys and seven non-numeric aggregate fields. All six derived-output producer lineages are now confirmed.

## Gates remaining before production consideration

1. Supply non-empty COR3, authorized HUD DRGR, Department of Justice cabilderos, and PRASA exports.
2. Run the comparison against the actual enriched `pr_entity_profiles.csv` when supplied.
3. Re-run the complete 151-source audit after valid source ingestion.
4. Certify source freshness and external-universe completeness.
5. Complete PR2.5/PR2.6 reconciliation before PR3 deduplication.
6. Validate production export and downstream federation consumers.
7. Keep promotion guards closed until every blocker is cleared.

## Preservation

PR #452 remains draft and unmerged. This roadmap does not authorize an additional merge, direct write to `main`, live fetch, credential automation, raw data commit, data promotion, production activation, force push, or history rewrite.
