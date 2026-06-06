# archive/r4_pipeline_legacy/

Historical one-shot remediation and rebuild passes from the R4 source-recovery
work, plus their paired tests. Moved here from `contract_sweeper/pipeline/` and
`tests/` during the Phase 3 audit cleanup (2026-06-06).

Mirrors the precedent set by `archive/r4_legacy/`.

## What's here and why

These 14 modules were one-shot remediation scripts written round-by-round to
unstick R4 backfill failures. The names alone say it — `final_backfill_retry`,
`partial_master_rebuild`, `targeted_backfill_retry`, etc. — and the existence
of `final_*` plus `*_retry` siblings already suggests the "final" wasn't.

[reports/codebase_audit.md](../../reports/codebase_audit.md) Phase 3 confirmed
each module had zero live imports outside of `tests/` and `archive/`. They're
not on any current execution path. Archiving (rather than deleting) preserves
the rebuild history if anyone needs to investigate why a particular round was
necessary.

### Modules

```
backfill_failure_remediation.py
backfill_readiness_audit.py
backfill_runner.py
controlled_backfill.py
controlled_backfill_execution.py
endpoint_patch_retry.py
final_backfill_retry.py
final_source_recovery_pass.py
partial_master_rebuild.py
partial_rebuild_gate.py
partial_rebuild_retry.py
producer_patch_retry.py
scoped_partial_rebuild.py
targeted_backfill_retry.py
```

### Paired tests

```
tests/test_backfill_failure_remediation_r48c.py
tests/test_backfill_readiness_audit_r48a.py
tests/test_backfill_runner_r47.py
tests/test_controlled_backfill_r48.py
tests/test_controlled_backfill_execution_r48b.py
tests/test_final_source_recovery_pass_r48i.py
tests/test_manual_fulfillment_endpoint_retry_r48h.py
tests/test_partial_master_rebuild_r49a.py
tests/test_scoped_unfreeze_retry_r49g.py
tests/test_source_materialization_rebuild_retry_r49b.py
tests/test_targeted_backfill_retry_r48d.py
```

Pytest's `norecursedirs = archive` (see `pytest.ini`) excludes this directory
from collection — the archived tests stay readable but don't run.

## What's NOT here

`source_recovery_pause_lock.py` stayed in `contract_sweeper/pipeline/`. The
audit's safety check found 2 live refs to it in `scripts/`
(`run_source_recovery_pause_lock_r49z.py`). It's still on a current path.

## Restoring a module

If you ever need one of these back on a live path:

```bash
git mv archive/r4_pipeline_legacy/<module>.py contract_sweeper/pipeline/
# and re-run the test under tests/ if applicable
```

Then update `contract_sweeper/pipeline/ARCHIVED.md` and this file.
