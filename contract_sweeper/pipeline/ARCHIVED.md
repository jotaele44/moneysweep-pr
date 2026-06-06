# Archived modules (2026-06-06)

The following one-shot remediation modules and their paired tests were moved to
[`archive/r4_pipeline_legacy/`](../../archive/r4_pipeline_legacy/) during the
Phase 3 audit cleanup. They had zero live imports outside `tests/` and `archive/`,
and their names made the historical-rebuild nature obvious.

| Module | Test |
|---|---|
| `backfill_failure_remediation.py` | `test_backfill_failure_remediation_r48c.py` |
| `backfill_readiness_audit.py` | `test_backfill_readiness_audit_r48a.py` |
| `backfill_runner.py` | `test_backfill_runner_r47.py` |
| `controlled_backfill.py` | `test_controlled_backfill_r48.py` |
| `controlled_backfill_execution.py` | `test_controlled_backfill_execution_r48b.py` |
| `endpoint_patch_retry.py` | _(no paired test)_ |
| `final_backfill_retry.py` | `test_manual_fulfillment_endpoint_retry_r48h.py` |
| `final_source_recovery_pass.py` | `test_final_source_recovery_pass_r48i.py` |
| `partial_master_rebuild.py` | `test_partial_master_rebuild_r49a.py` |
| `partial_rebuild_gate.py` | _(no paired test)_ |
| `partial_rebuild_retry.py` | `test_source_materialization_rebuild_retry_r49b.py` |
| `producer_patch_retry.py` | _(no paired test)_ |
| `scoped_partial_rebuild.py` | `test_scoped_unfreeze_retry_r49g.py` |
| `targeted_backfill_retry.py` | `test_targeted_backfill_retry_r48d.py` |

`source_recovery_pause_lock.py` stayed — 2 live refs in `scripts/`.

See [reports/codebase_audit.md](../../reports/codebase_audit.md) Phase 3 for
the audit rationale and inbound-import survey.
