# Promotion Guard

Governance artifact for issue #86 — prevents a non-validated build from
being promoted to the `master`/`main` branch as a production-ready release.

## What it does

The guard reads the machine-readable project state and decides whether the
current build may be promoted. It does **not** restrict ordinary diagnostic
development: a normal pull request to `main` always passes.

- Implementation: `contract_sweeper/validation/promotion_guard.py`
- CLI: `scripts/run_promotion_guard.py`
- CI: `.github/workflows/promotion-guard.yml`
- Tests: `tests/test_promotion_guard.py`

## Promotion claim

A *promotion claim* is any `production_status` in `reports/current_status.json`
that is **not** one of the diagnostic tiers:

- `NON_PRODUCTION_DIAGNOSTIC`
- `PARTIAL_AVAILABLE_SOURCE_COVERAGE`
- `COMPLETE_AVAILABLE_SOURCE_COVERAGE`

Any other value (for example `MVP_VALIDATED`, `FINANCIAL_VALIDATED`,
`PRODUCTION_VALIDATED`, or an unrecognised string) is treated as a claim of
production readiness and triggers the evidence checks below. An unrecognised
status fails closed — it requires evidence rather than passing silently.

## Evidence required for promotion

When a promotion claim is present, **all** of the following must hold:

1. `pause_lock_active` is not `true`.
2. `last_tests.status` is `GREEN` with `failed == 0`.
3. `secrets_audit.findings == 0` and `real_keys_in_repo` is not `true`.
4. `data/exports/production_status.json` exists (run
   `scripts/run_production_status_gate.py`), its `production_status` is not
   `NON_PRODUCTION_DIAGNOSTIC`, and `blocker_count == 0`.

If any condition fails, the guard exits non-zero and the CI check fails,
blocking the merge to `master`.

## Running locally

```bash
python scripts/run_promotion_guard.py --root .
python scripts/run_promotion_guard.py --root . --json
```

Exit code `0` means eligible (or no promotion claimed); exit code `1` means
promotion is blocked.

## Relationship to the production-status gate

`.github/workflows/production-status-gate.yml` enforces that the repository
*stays* in `NON_PRODUCTION_DIAGNOSTIC` while phase locks are active. The
promotion guard is complementary: it defines the conditions under which an
*intentional* escalation to a validated tier is permitted to reach `master`.
See `docs/PRODUCTION_GATES.md` for the full gate ladder.
