# Materialization Operator Checklist

Use this checklist before and after running source materialization.

## Pre-Run Checklist

- [ ] Working tree is clean or unrelated local deltas are stashed.
- [ ] Dependencies are installed with `pip install -r requirements.txt`.
- [ ] `.env` exists locally.
- [ ] Real API keys are present where needed.
- [ ] No secrets are committed.
- [ ] Manual-export sources are intentionally included or intentionally excluded.
- [ ] `python3 run_all.py --only-setup --strict-preflight` passes.
- [ ] `python3 -m pytest tests/test_materialization_readiness.py -q` passes.
- [ ] `python3 scripts/check_network_egress.py` passes in the materialization environment.
- [ ] Operator understands that success is measured against the automatable subset.

## Run Checklist

- [ ] Adapter-backed sources are run through `python3 -m moneysweep.query --source <source_id>`.
- [ ] Producer-backed sources are run through `python3 run_all.py --strict-preflight`.
- [ ] Scoped runs use documented `--skip-*` flags.
- [ ] Failures are captured with command, exit code, last 40 lines, changed files, and suspected area.

## Post-Run Checklist

- [ ] `python3 scripts/gap_analysis_builder.py` has been run.
- [ ] `python3 scripts/build_source_recovery_matrix.py` has been run.
- [ ] `reports/materialization_readiness.json` shows `automatable_ready == automatable_total`.
- [ ] Automatable sources in `reports/gap_analysis_report.json` are fully materialized.
- [ ] Queued sources remain classified as manual export, scraper needed, deferred stub, semantic duplicate, or broken producer.
- [ ] Generated reports are reviewed before commit.
- [ ] No raw secrets, credentials, or private manual exports are staged.
