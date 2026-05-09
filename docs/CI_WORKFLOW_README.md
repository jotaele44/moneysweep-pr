# CI Workflow README

R4.9Z-D adds two push and pull request workflows that automate only the existing safe checks used while source recovery is paused.

## Workflows

| Workflow | File | Purpose |
| --- | --- | --- |
| Contract Sweeper CI | `.github/workflows/ci.yml` | Installs repository dependencies, compiles `contract_sweeper` and `tests`, then runs the test suite. |
| Production Status Gate | `.github/workflows/production-status-gate.yml` | Runs the production status gate and repo quality audit, then enforces the diagnostic production state and Phase 7/8 block. |

Both workflows run on:

- `pull_request`
- `push`

## Allowed Commands

The workflows are limited to these repository checks:

```bash
python -m compileall contract_sweeper tests
pytest -q
python scripts/run_production_status_gate.py --root .
python scripts/run_repo_quality_audit_r49z_b.py --root .
```

## Safety Boundaries

The CI workflows do not require secrets, do not print environment variables, and do not call source acquisition or downstream production execution jobs.

The workflows must not run:

- source download scripts;
- endpoint retry scripts;
- source ingestion scripts;
- source staging jobs;
- master rebuild jobs;
- graph rebuild jobs;
- risk engine jobs;
- report generation jobs.

## Gate Behavior

`Production Status Gate` fails if `data/exports/production_status.json` reports anything other than `NON_PRODUCTION_DIAGNOSTIC`.

It also fails if `data/exports/rebuild_status.json` no longer reports `phase_7_8_blocked: true`.

After the repo quality audit, it additionally checks:

- `production_status` remains `NON_PRODUCTION_DIAGNOSTIC`;
- `phase_7_8_blocked` remains `true`;
- `downloads_executed` remains `false`;
- `rows_ingested` remains `0`;
- `production_inputs_staged` remains `0`.

## Local Validation

Before changing these workflows, run:

```bash
python -m compileall contract_sweeper tests
pytest -q
python scripts/run_production_status_gate.py --root .
```

If `run_production_status_gate.py` rewrites timestamped diagnostic artifacts locally, restore those generated side effects before committing workflow or documentation changes.

