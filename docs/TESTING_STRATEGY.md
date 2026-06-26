# Testing Strategy

R4.9Z-F adds pytest marker definitions and a file-level test inventory while preserving the existing full-suite behavior. No test file was modified to skip, xfail, or exclude currently passing tests from default `pytest -q`.

## Default Test Command

Use the full suite as the default quality gate:

```bash
pytest -q
```

This remains the command used by the paused-state validation workflow. Marker definitions are available for future selection, but R4.9Z-F does not add a default marker filter.

## Markers

| Marker | Use |
| --- | --- |
| `unit` | Pure logic tests with minimal filesystem or process coupling. |
| `integration` | Multi-module or filesystem-backed behavior tests. |
| `pipeline_gate` | Production, pause, recovery, blocker, or phase-gate invariant tests. |
| `non_executing` | Audits, docs, configuration, validation, and status checks that do not execute source recovery. |
| `external` | Tests around external source boundaries or downloader modules. These remain included by default unless an operator explicitly filters them in a future workflow. |
| `slow` | Long-running tests reserved for explicit selection. No tests are marked slow by default in R4.9Z-F. |

## Inventory

The file-level inventory is written to:

```text
data/exports/test_inventory_r4_9z_f.csv
```

It records each `tests/test_*.py` file, the number of top-level `test_` functions found, suggested marker categories, default pytest behavior, and the heuristic used for categorization.

The categorization is advisory. It does not alter collection, selection, skip behavior, xfail behavior, or production status gates.

## Pause Safety

Testing work remains inside the R4.9Z pause rules:

- no source downloads;
- no endpoint retries;
- no source ingestion;
- no production staging;
- no master rebuilds;
- no graph rebuilds;
- no risk jobs;
- no report generation jobs;
- no R4.9G/R5/R6/R7/R8/R9/R10 starts.

The production status must remain `NON_PRODUCTION_DIAGNOSTIC`, and Phase 7/8 must remain blocked.

## Validation Gates

Before merging marker or testing strategy changes, run:

```bash
python -m compileall moneysweep tests
pytest -q
python scripts/run_production_status_gate.py --root .
python scripts/run_repo_quality_audit_r49z_b.py --root .
```

If the production status gate or repo quality audit rewrites timestamped diagnostic artifacts locally, restore those generated side effects before committing marker or documentation changes.

