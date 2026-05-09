# Operator Next Actions After R4.9Z-A

Generated at: 2026-05-09T05:47:50Z

## Current Locked State

- production_status: NON_PRODUCTION_DIAGNOSTIC
- phase_7_8_blocked: True
- pause_lock_active: True
- retry_suppression_active: True
- downstream_blockers_active: True
- unfreeze_candidates: 0
- sources_still_missing: 21

## Required External Actions

1. Deliver source files listed in `data/review_queue/source_recovery_resume_conditions_r4_9z.csv`.
2. Ensure each delivered file satisfies filename pattern, required columns, nonzero rows, and SHA256 checks.
3. Keep source files in approved paths only (`data/manual_import_dropzone/**` and planned staging paths).

## What To Run After Delivery

1. Re-run watch guard only after delivery: `python scripts/run_source_delivery_watch_r49f.py --root .`
2. Re-run pause lock check: `python scripts/run_source_recovery_pause_lock_r49z.py --root .`
3. Do not start R5/R6/R7/R8 until unfreeze candidates are validated and blockers are explicitly reduced.

## Prohibited Until Unfreeze

- Do not run download retries.
- Do not ingest rows.
- Do not stage production inputs.
- Do not begin R5/R6/R7/R8.
