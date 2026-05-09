# CI Testing Strategy

## Purpose

Keep the repository stable while source recovery remains externally blocked.

## Core Gates

1. Compile gate: `python -m compileall contract_sweeper tests`
2. Test gate: `pytest -q`
3. Production-status gate: `python scripts/run_production_status_gate.py --root .`

## Phase-Lock Invariants

1. `production_status` must remain `NON_PRODUCTION_DIAGNOSTIC`
2. `phase_7_8_blocked` must remain `true`
3. Retry suppression must remain active until unfreeze candidates validate
4. Downstream blockers must remain active for R5/R6/R7/R8

## Safety Policy

1. No download retries in pause-locked phases
2. No source ingestion in pause-locked phases
3. No production staging in pause-locked phases
4. No synthetic production rows
