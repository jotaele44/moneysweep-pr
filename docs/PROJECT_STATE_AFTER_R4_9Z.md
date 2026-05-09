# Project State After R4.9Z

This repository is intentionally paused after PR #41. The pause is not a failure of the hardening track. It is the expected state until external source files or access materially change.

## Current State

- Branch baseline: `origin/main` after PR #41.
- Production status: `NON_PRODUCTION_DIAGNOSTIC`.
- Pause lock: active.
- Retry suppression: active.
- Downstream blockers: active.
- Phase 7/8 block: active.
- Unfreeze candidates: `0`.
- Source delivery blockers: `21`.
- Manual source files still missing: `14`.
- Physical validated source files still missing: `7`.
- Builder expected inputs: `21`.
- Builder present inputs: `0`.

The status is documented by:

- `docs/SOURCE_RECOVERY_PAUSE_STATUS_R4_9Z.md`
- `docs/OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md`
- `docs/REPO_QUALITY_STATUS_AFTER_R4_9Z.md`
- `data/exports/rebuild_status.json`

## Why Production Rebuild Is Blocked

The production master rebuild cannot proceed because all required production source inputs remain unavailable to the checked-in repo state. The rebuild status still reports every expected builder input missing, and R4.9F reports no unfreeze candidates.

No downstream phase should infer production readiness from the presence of stale summaries, cached outputs, fixture-like reports, or diagnostic artifacts. The current status is deliberately `NON_PRODUCTION_DIAGNOSTIC` until real source coverage is restored and the production gates pass.

## Missing Source Inputs

The missing source inventory is authoritative in:

- `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`
- `data/review_queue/source_delivery_checklist_r4_9e.csv`

The blocked set contains these target outputs:

| Count | Blocker class | Meaning |
| ---: | --- | --- |
| 14 | `manual_file_required` | A source file must be delivered into an approved manual dropzone before any retry can unfreeze. |
| 7 | `physical_validated_file_missing` | A previously represented validated source must be restored at the target output path with a manifest-compatible hash. |
| 21 | total | No production rebuild retry is available while all 21 remain blocked. |

## Approved Delivery Paths

Manual deliveries belong only under the dropzones listed in `data/review_queue/source_delivery_checklist_r4_9e.csv`, currently rooted at:

- `data/manual_import_dropzone/r4_8e/usaspending_federal_awards_backbone/`
- `data/manual_import_dropzone/r4_8e/fsrs_subawards/`
- `data/manual_import_dropzone/r4_8e/fema_pa_hmgp/`
- `data/manual_import_dropzone/r4_8e/federal_research/`
- `data/manual_import_dropzone/r4_8e/sba_loans/`
- `data/manual_import_dropzone/r4_8e/hud_cdbg/`
- `data/manual_import_dropzone/r4_8e/federal_sectoral_sbir/`
- `data/manual_import_dropzone/r4_8e/federal_sectoral_usace/`

Physical validated restorations belong at the target output path listed in `data/review_queue/physical_validated_files_still_missing_r4_9c.csv`.

Do not treat files outside those approved paths as production inputs.

## Allowed Work While Paused

These tracks are allowed:

- Source acquisition outside the repo, producing files or access changes only.
- Documentation and operator clarity work.
- CI, security, dependency, and test hardening that does not execute source recovery or change pipeline behavior.

These tracks are blocked:

- R4.9G retry.
- R5 entity resolution.
- R6 execution chains.
- R7 financial backbone.
- R8 graph rebuild.
- R9 risk engine.
- R10 reports.

## Validation Gates

Safe repository quality checks while paused:

```bash
python -m compileall contract_sweeper tests
pytest -q
python scripts/run_production_status_gate.py --root .
```

The production status gate must continue to report `NON_PRODUCTION_DIAGNOSTIC`, and Phase 7/8 must remain blocked.

