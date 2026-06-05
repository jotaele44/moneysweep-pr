# Federation Interface — Contract-Sweeper / moneysweep-pr

## Active Vector

`CONTRACT_SWEEPER_FEDERATION_READINESS_AUDIT`

## Purpose

This document defines how the Hub should discover and call this repository as the Puerto Rico public-money intelligence node of the wider code Federation.

The historical repository name is `Contract-Sweeper`. The Federation program role is `moneysweep-pr`.

## Current Gate

| Gate | Status |
|---|---|
| Hub discovery | Ready |
| Live Hub execution | Not ready |
| Producer execution | Requires strict preflight |
| Production promotion | Blocked until source materialization and validation |

## Source-Count Truth

The current source-count truth is maintained in:

```text
reports/materialization_readiness.json
```

Current canonical count:

| Metric | Value |
|---|---:|
| Total sources | 84 |
| Automatable sources | 54 |
| Automatable ready | 54 |
| Queued/excluded | 30 |
| Broken producers | 0 |

Queued/excluded breakdown:

| Class | Count |
|---|---:|
| manual_export | 10 |
| scraper_needed | 15 |
| semantic_duplicate | 3 |
| deferred_stub | 2 |
| broken_producer | 0 |

Older status text may reference 82 sources. Federation consumers must treat `reports/materialization_readiness.json`, `federation.json`, and `reports/federation_source_status_reconciliation.json` as current control-plane truth.

## Hub Callable Commands

| Hub Action | Command | Network | Notes |
|---|---|---|---|
| setup | `python3 run_all.py --only-setup` | No required live fetch | Creates directory/instruction scaffolding |
| strict_preflight | `python3 run_all.py --only-setup --strict-preflight` | No producer execution | Required before materialization |
| full_pipeline | `python3 run_all.py --strict-preflight` | Yes | Only in egress-enabled environment |
| materialization_matrix | `python3 scripts/build_source_recovery_matrix.py` | No live producer execution | Regenerates recovery/readiness surfaces |
| gap_matrix | `python3 scripts/gap_analysis_builder.py` | No live producer execution | Regenerates source-registry status surfaces |
| test_suite | `python3 -m pytest tests/ -q` | No intended network | Baseline regression gate |
| dashboard_export | `python3 scripts/build_dashboard_explorer.py` | No intended network | Builds static dashboard |
| foia_letters | `python3 scripts/build_foia_letters.py` | No intended network | Builds request-letter outputs from queue/config |
| ngo_layer | `python3 scripts/ngo_integration.py` | No live bulk download | Runs on dropped-in NGO/OSFL files |

## Required Runtime Keys

The following keys are local runtime requirements and must never be committed:

```text
FEC_API_KEY
HIGHERGOV_API_KEY
LDA_API_KEY
OPENCORPORATES_API_TOKEN
SAM_API_KEY
```

Missing keys are not structural repo defects. They limit or skip key-gated producers.

## Canonical Federation Outputs

| Output | Path |
|---|---|
| Repo manifest | `federation.json` |
| Current status | `reports/current_status.json` |
| Materialization readiness | `reports/materialization_readiness.json` |
| Source-status reconciliation | `reports/federation_source_status_reconciliation.json` |
| Source recovery matrix | `reports/source_recovery_matrix.csv` and `.md` |
| Top-form gap matrix | `reports/top_form_gap_matrix.csv` |
| Readiness audit | `reports/federation_readiness_audit.md` |
| Dashboard | `exports/dashboard/index.html` |
| Graph nodes | `exports/graph/nodes.csv` |
| Graph edges | `exports/graph/edges.csv` |

## Federation Rules

1. The Hub may discover this repo now.
2. The Hub must not treat it as production-live until manual ingestion, scraper-needed sources, runtime keys, and post-materialization validation are cleared.
3. The Hub must call strict preflight before any live producer execution.
4. No source may be marked fully materialized until canonical outputs, schema validation, and regression tests pass.
5. Historical repo name remains valid, but Federation naming should refer to the node as `moneysweep-pr`.

## Next Vector

```text
EXECUTE_NEXT_VECTOR: PREP_TRANCHE_B_MANUAL_SOURCE_INGESTION
```
