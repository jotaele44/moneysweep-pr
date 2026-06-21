# Federation Readiness Audit

## Active Vector

`PREP_TRANCHE_B_MANUAL_SOURCE_INGESTION`

## Audit Scope

This audit evaluates the repository from current control-plane state to Federation preparedness. It does not execute producers, ingest source files, scrape external sources, transform data, or promote production outputs.

## Repository Role

| Field | Value |
|---|---|
| Historical repo name | `Contract-Sweeper` |
| Federation node name | `moneysweep-pr` |
| Hub parent | `thehub-pr` |
| Jurisdiction | Puerto Rico |
| Program role | Public-money intelligence node |
| Current status | Non-production diagnostic |

## Evidence Base

| Evidence Tier | File / Surface | Use |
|---|---|---|
| T1 | `reports/materialization_readiness.json` | Current source-count truth |
| T1 | `reports/current_status.json` | Historical status and active vector record |
| T1 | `run_all.py` | Callable pipeline surface |
| T1 | `scripts/pipeline_preflight.py` | Strict preflight gate |
| T1 | `.github/workflows/tests.yml` | CI baseline |
| T1 | `.gitignore` | Data/secrets handling |
| T1 | `reports/top_form_gap_matrix.csv` | Current gap and blocker matrix |

## Current Readiness Summary

| Dimension | Status | Finding |
|---|---|---|
| Source registry | Strong, not final | 136 total sources are declared in current readiness truth |
| Automatable surface | Ready for controlled execution | 77/77 automatable sources are ready |
| Broken producers | Clear | 0 broken producers recorded |
| Runtime credentials | Operator-dependent | 8 keys must be supplied locally |
| Manual ingestion | Not complete | 39 manual-export sources remain queued/excluded |
| Scraper queue | Not complete | 15 sources require scraper/adaptor work |
| Hub discovery | Ready | `federation.json` and interface documentation now define discovery contract |
| Live Hub execution | Not ready | Materialization, keys, and validation remain unresolved |

## Federation Readiness Score

| Layer | Score | Basis |
|---|---:|---|
| Repo structure | 85% | Existing scripts, docs, registries, tests, reports |
| Control-plane truth | 90% | Source-count reconciliation complete; all federation-facing files updated to 136-source truth |
| Hub discoverability | 90% | Manifest and interface contract now added |
| Live execution readiness | 60% | Strict preflight exists, but live materialization still blocked |
| Data reproducibility | 75% | Output policy exists; generated data must still be regenerated after materialization |
| Security posture | 80% | Secret/data ignores exist; runtime keys remain local operator responsibility |
| Overall | 78% | Good for Federation discovery; not ready for production execution |

## Gap Matrix

| Priority | Gap | Required Fix | Owner |
|---|---|---|---|
| DONE | Source-count reconciliation | Updated all Federation-facing files to 136-source truth (2026-06-21) | GPT / Claude |
| P0 | Hub callable contract | Keep `federation.json` and `docs/FEDERATION_INTERFACE.md` stable | GPT / Claude |
| P0 | Strict preflight dependency | Require strict preflight before producer execution | GPT / Claude |
| P0 | Manual source ingestion | Build Tranche B parsers, schemas, outputs, tests | GPT / Claude |
| P0 | Runtime keys | Provide local `.env` values for 8 key-gated sources | Operator |
| P1 | Scraper-needed queue | Build PR-gov scraping adapters for queued sources | GPT / Claude |
| P1 | Materialization proof | Regenerate source recovery/readiness matrices after runs | GPT / Claude |
| P1 | Output promotion | Promote only after canonical outputs validate | GPT / Claude |
| P2 | Historical wording cleanup | Normalize older 82-source references in a dedicated cleanup PR if needed | GPT / Claude |

## Federation Decision

| Question | Decision |
|---|---|
| Should the Hub discover this repo now? | Yes |
| Should the Hub execute live producers now? | No |
| Should this repo be treated as production-ready? | No |
| Should Tranche B proceed next? | Yes |

## Blind Spots

| Blind Spot | Risk | Mitigation |
|---|---|---|
| No producer execution in this pass | Runtime failures may remain hidden | Run strict preflight and targeted tests in local/CI environment |
| Manual files not parsed in this pass | Tranche B source quality unknown | Build parser-level tests from representative fixtures |
| Scraper-needed queue unresolved | Coverage remains incomplete | Queue separate scraper adapter PRs after Tranche B |
| Runtime keys absent from repo by design | Key-gated producers cannot be fully validated in repo-only audit | Validate with local `.env` and CI-safe secret configuration |

## Next Gate

```text
EXECUTE_NEXT_VECTOR: EXEC_TRANCHE_B_MANUAL_SOURCE_INGESTION
```
