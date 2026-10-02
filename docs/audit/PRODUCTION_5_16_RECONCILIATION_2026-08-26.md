# MoneySweep Production 5/16 Reconciliation — 2026-08-26

## State

**AUDITED OPERATIONAL RESIDUE — NOT PRODUCTION VALIDATION**

This record reconciles the committed R4.9F operational watch artifacts against
the current canonical 158-source registry without promoting legacy family names,
external file locations, filenames, or historical manifests into current source
identity.

The immutable desktop pre-hardening baseline remains
`aa39052cc99d5331fe875196d5853c9d10d0730e`. Candidate 1 and Candidate 2 retain
their previously frozen certification states. This document creates no Candidate
3 and awards no production credit.

## Canonical denominator

- registered sources: `158`
- automatable sources: `109`
- queued/excluded: `49`
- source-ID-set SHA-256:
  `673659d9c53e8428e21052d95819ff35023e90142756686e73a9c9f1b326bbf2`

The R4.9F watch is a narrower operational checklist. Its committed status reports
21 checklist rows, 5 unfreeze candidates, 16 sources still missing, zero rows
ingested, zero production inputs staged, and
`NON_PRODUCTION_DIAGNOSTIC`. Those counts are not a replacement source
registry denominator.

## Five unfreeze candidates

All five committed candidates came from the historical
`usaspending_federal_awards_backbone` recovery family. Their observed old local
paths are evidence locations only; they do not establish canonical identity or
promotion.

| candidate | rows | SHA-256 | current identity adjudication |
| --- | ---: | --- | --- |
| `data/staging/processed/pr_contracts_master.csv` | 68680 | `c71fb68214e5079daaa4f9d5f3952b499bb06d49451eb7a35baac6a61dd97a1c` | **BINDING CANDIDATE:** exact canonical output of `usaspending_prime`; still requires controlled intake/validation before promotion |
| `data/staging/expansion/expansion_idv_indirect_pr.csv` | 540 | `893f6d0aa4612f1b189452d05f032913545a894f4dc0b29dd840147149b9c63f` | **RECOVERY INPUT / DERIVED:** not a distinct canonical registry source ID |
| `data/staging/expansion/expansion_dod_upr_2001_2015.csv` | 1901 | `e4bfa0a20fffa2a97d4e87b77043aa9acce5b0aa244183a70ed0844000115013` | **RECOVERY INPUT / DERIVED:** not a distinct canonical registry source ID |
| `data/staging/expansion/expansion_dod_upr_2016_2025.csv` | 2774 | `a4f7b0a5a7c63070ef7482522716458d3eafdce73b7ea81a86d575143b6aff9c` | **RECOVERY INPUT / DERIVED:** not a distinct canonical registry source ID |
| `data/staging/expansion/expansion_reconstruction_2017_2025.csv` | 1356 | `c08e70c9539f0a1de4fd2e8c739aa6a63f1a5a80db0227d7537dd08c8f71279f` | **RECOVERY INPUT / DERIVED:** not a distinct canonical registry source ID |

No candidate above is production-valid merely because it has nonzero rows and a
hash. The existing R4.9F contract requires controlled delivery, required-column
validation, nonzero rows, and staging through the declared recovery path.

## Sixteen still-missing operational inputs

Identity is assigned only when the exact current registry declares the exact
expected output. Legacy family labels are retained separately.

| # | operational expected input | R4.9F family | current canonical source-ID adjudication | state |
| ---: | --- | --- | --- | --- |
| 1 | `data/staging/processed/pr_doe_master.csv` | `federal_sectoral_doe` | `doe_grants` | **BOUND_BY_EXACT_OUTPUT** |
| 2 | `data/staging/processed/pr_grants_master.csv` | `usaspending_federal_awards_backbone` | `grants_gov` | **BOUND_BY_EXACT_OUTPUT** |
| 3 | `data/staging/processed/pr_dot_master.csv` | `federal_sectoral_dot` | `dot_grants` | **BOUND_BY_EXACT_OUTPUT** |
| 4 | `data/staging/processed/pr_subawards_master.csv` | `fsrs_subawards` | `usaspending_subawards` | **BOUND_BY_EXACT_OUTPUT; LEGACY_FAMILY_CONTRADICTION** |
| 5 | `data/staging/processed/pr_epa_master.csv` | `federal_sectoral_epa` | `epa_grants` | **BOUND_BY_EXACT_OUTPUT** |
| 6 | `data/staging/processed/pr_fema_pa_master.csv` | `fema_pa_hmgp` | `fema_pa_openfema_v2` | **BOUND_BY_EXACT_OUTPUT; FAMILY_TOO_BROAD** |
| 7 | `data/staging/processed/pr_hud_master.csv` | `hud_cdbg` | no current exact output binding found | **LEGACY_ORPHAN_UNRESOLVED** |
| 8 | `data/staging/processed/pr_fema_hmgp_master.csv` | `fema_pa_hmgp` | `fema_hmgp` | **BOUND_BY_EXACT_OUTPUT** |
| 9 | `data/staging/processed/pr_slfrf_master.csv` | `slfrf` | `slfrf` | **BOUND_BY_EXACT_OUTPUT** |
| 10 | `data/staging/processed/pr_research_master.csv` | `federal_research` | `research_grants` | **BOUND_BY_EXACT_OUTPUT** |
| 11 | `data/staging/processed/pr_usda_master.csv` | `federal_sectoral_usda` | `usda_grants` | **BOUND_BY_EXACT_OUTPUT** |
| 12 | `data/staging/processed/pr_sba_loans_master.csv` | `sba_loans` | `sba_loans` | **BOUND_BY_EXACT_OUTPUT** |
| 13 | `data/staging/processed/pr_wioa_grants.csv` | `federal_sectoral_wioa` | `wioa` | **BOUND_BY_EXACT_OUTPUT** |
| 14 | `data/staging/processed/pr_cdbg_dr_master.csv` | `hud_cdbg` | `hud_cdbg_dr_public` | **BOUND_BY_EXACT_OUTPUT; FAMILY_TOO_BROAD** |
| 15 | `data/staging/processed/pr_sbir_master.csv` | `federal_sectoral_sbir` | current `sbir` declares `data/staging/processed/pr_sbir.csv`, not this path | **OUTPUT_IDENTITY_MISMATCH_UNRESOLVED** |
| 16 | `data/staging/processed/pr_usace_civil_master.csv` | `federal_sectoral_usace` | `usace_civil_works` | **BOUND_BY_EXACT_OUTPUT** |

### Legacy HUD contradiction

A historical R4.8D validated manifest exists for
`data/staging/processed/pr_hud_master.csv`, with:

- source system: `hud_cdbg`
- producer: `scripts/download_hud.py`
- rows: `619`
- SHA-256:
  `8d5da1cafe28d93f5010ffcac44047483990af476a1c19b9400547483bf126f5`

On the current branch, `scripts/download_hud.py` does not exist and the current
registry does not declare `pr_hud_master.csv` as an expected output of
`hud_cdbg_dr_public` or another source inspected in this reconciliation. The
historical manifest is therefore preserved as historical evidence only. It is
not promoted through the broad `hud_cdbg` family name.

### SBIR output contradiction

The operational watch expects `data/staging/processed/pr_sbir_master.csv`, while
the current canonical `sbir` entry declares
`data/staging/processed/pr_sbir.csv`. Filename similarity and shared SBIR context
are insufficient to declare these manifestations identical. A migration or
explicit authoritative binding is required before the old operational row can be
closed.

### Subaward family contradiction

The R4.9F row labels `pr_subawards_master.csv` as `fsrs_subawards`. The current
registry binds that exact output to `usaspending_subawards`; the current
`fsrs_subawards` source instead declares `pr_fsrs_subawards.csv`. The output path
therefore controls current identity, while the legacy family label is preserved
as a contradiction.

## Historical manifests do not override current registry identity

Historical R4.8D validated manifests remain useful for byte/row lineage. The
committed manifest set includes, among others, SLFRF, DOT, USDA, DOE, HUD, EPA,
USACE Civil Works, and WIOA files. A historical `validation_status=validated`
does not by itself satisfy current required-column, source-ID, or production
promotion contracts.

## Closure requirements

For each of the 14 exact-output-bound rows:

1. obtain or materialize the correct physical source manifestation;
2. preserve exact bytes and SHA-256;
3. validate nonzero rows where required;
4. validate the current required-column contract;
5. bind to the exact canonical source ID and current producer/adapter;
6. create/update a current manifest with lineage;
7. stage through the approved path;
8. rerun source recovery and production gates.

For `pr_hud_master.csv` and `pr_sbir_master.csv`, first resolve the identity
collision. They receive no production credit while unresolved.

For the four expansion candidates, validate them only as recovery/materialization
inputs. Do not mint additional source IDs or increment the 158-source denominator.

## Production boundary

The current production state remains `NON_PRODUCTION_DIAGNOSTIC`. This audit does
not alter the production arithmetic and does not authorize the historical
partial corpus, fixture-like 18-entity graph, or any source candidate for
production use.

`PRODUCTION_VALIDATED` may be emitted only by the normal exact-checkout gate after
all applicable source, schema, lineage, duplicate, temporal, identity, and
synthetic-data checks pass.
