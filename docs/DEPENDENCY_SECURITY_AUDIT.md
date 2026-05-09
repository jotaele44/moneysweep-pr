# Dependency Security Audit (R4.9Z-E)

Generated at: 2026-05-09T07:23:12Z

## Scope

This audit inspected tracked repository files only. It did not run network calls, source downloads, endpoint retries, ingestion, source staging, rebuilds, graph jobs, risk jobs, or report generation.

Dependency versions were not changed.

## Gate Result

- r4_9z_e_gate_passed: True
- production_status: NON_PRODUCTION_DIAGNOSTIC
- phase_7_8_blocked: True
- dependency_changes_made: False
- downloads_executed: False
- rows_ingested: 0
- production_inputs_staged: 0

## Dependency Files Checked

| File | Status |
| --- | --- |
| `requirements.txt` | present and inspected |
| `pyproject.toml` | absent |
| `setup.py` | absent |
| `setup.cfg` | absent |

## Dependency Summary

| Metric | Count |
| --- | ---: |
| Direct dependencies | 7 |
| Pinned dependencies | 0 |
| Range-pinned dependencies | 7 |
| Unpinned dependencies | 0 |
| Transitive-only declarations | 0 |
| Unknown declarations | 0 |
| Broad lower-bound-only ranges | 7 |
| Duplicate package declarations | 0 |

All direct dependencies in `requirements.txt` use lower-bound-only range pins. That is better than fully unpinned dependencies, but it still permits unreviewed major-version upgrades in future installs. This phase documents the issue only; a later dependency remediation PR should decide whether to introduce upper bounds or a lockfile.

## Direct Dependency Inventory

| Package | Declaration | Posture | Notes |
| --- | --- | --- | --- |
| `pandas` | `pandas>=2.0.0` | range-pinned | Lower-bound-only range; heavy dependency. |
| `requests` | `requests>=2.28.0` | range-pinned | Lower-bound-only range. |
| `lxml` | `lxml>=4.9.0` | range-pinned | Lower-bound-only range; native/system dependency risk. |
| `pytest` | `pytest>=7.0.0` | range-pinned | Lower-bound-only range; test dependency. |
| `rapidfuzz` | `rapidfuzz>=3.0.0` | range-pinned | Lower-bound-only range; native wheel dependency risk. |
| `python-dotenv` | `python-dotenv>=1.0.0` | range-pinned | Lower-bound-only range; secret-loading helper. |
| `pyarrow` | `pyarrow>=14.0.0` | range-pinned | Lower-bound-only range; heavy native dependency. |

## High-Risk Dependency Conditions

Open followups were written to `data/review_queue/dependency_security_followups_r4_9z_e.csv` for:

- lower-bound-only version ranges across all direct dependencies;
- obvious native or heavy dependencies: `pandas`, `lxml`, `rapidfuzz`, and `pyarrow`;
- the existing manual-only HigherGov fetch workflow, which uses an optional GitHub secret and source-fetch script outside push/pull request CI.

No duplicate package declarations were found. No clearly unused heavy dependency was removed or changed in this phase.

## CI Workflow Review

Push/pull request CI workflows inspected:

- `.github/workflows/ci.yml`
- `.github/workflows/production-status-gate.yml`
- `.github/workflows/tests.yml`

Manual workflow inspected separately:

- `.github/workflows/highergov-fetch.yml`

CI findings:

- ci_secret_required: False
- ci_forbidden_job_count: 0
- environment-variable print commands found in CI: 0

The CI workflows do not require secrets, do not print environment variables, and do not invoke source download, endpoint retry, ingest, staging, rebuild, graph, risk, or report-generation jobs.

The existing `HigherGov fetch` workflow is `workflow_dispatch` only and remains outside the CI gate. It can call `scripts/fetch_highergov_api.py` when manually confirmed and when `HIGHERGOV_API_KEY` exists. It should remain manual-only while source recovery is paused.

## Secret Scan Summary

Tracked text files were scanned for:

- API key-like strings;
- private key headers;
- bearer tokens;
- AWS-style keys;
- generic long token, secret, password, and API key assignments.

Possible secret findings: 0.

No secret values were printed or written to the audit artifacts.

