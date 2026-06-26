# Production resumption checklist

The pipeline is intentionally paused at `production_status =
NON_PRODUCTION_DIAGNOSTIC` with `phase_7_8_blocked = true` (enforced by
`.github/workflows/production-status-gate.yml`). This checklist is the ordered
set of preconditions that must **all** hold before that status may be flipped and
the production phases unblocked. It exists so resumption is a deliberate,
verifiable act — not an accidental edit to a status file (Wave M, task 74).

## Why this is gated in CI

`production-status-gate.yml` runs the **source preflight** (`run_all.py
--only-setup --strict-preflight`) on every push/PR. If the structural preflight
is red, the gate is red, so **no change that flips the status can merge while
preflight is failing**. The diagnostic lock (`production_status` must stay
`NON_PRODUCTION_DIAGNOSTIC`, `phase_7_8_blocked` must stay `true`) remains the
backstop: flipping it is a separate, deliberate maintainer action taken **only
after** every box below is checked.

## Checklist (all must pass)

1. **Structural preflight is green.** `python3 run_all.py --only-setup
   --strict-preflight` exits 0 (run in CI by the production-status gate).
2. **Source coverage meets target.** `python -m
   moneysweep.runtime.validation_gates --root .` shows
   `source_coverage_rate` ≥ its threshold (currently 0.85) with required sources
   materialized — not the bootstrap empty state.
3. **Validation gates pass on real data.** The R5 gates (entity resolution,
   entity-type assignment, corporate parent UEI, linkage, duplicate rate,
   secret-leakage-zero) pass without `--allow-failed`.
4. **Risk-signal gates pass.** `python -m
   moneysweep.runtime.risk_signal_gates --root .` exits 0.
5. **Federation conformance is fresh.** `tests/test_conformance_fixture_freshness.py`
   passes — the committed export package matches its manifest and the contract
   version is consistent across the manifest/sample/schema.
6. **Full test suite green** at or above the coverage floor (`make test`).
7. **No oversized blobs / clean history posture.** `size-guard` is green and the
   `docs/HISTORY_PURGE_PLAN.md` purge has been completed (or consciously
   deferred) — see that doc.
8. **Lineage + provenance complete.** Every promoted master has source→output
   lineage registered and manifests written.

## Flipping the status (only after 1–8)

1. Update `data/exports/production_status.json` (`production_status`) and
   `data/exports/rebuild_status.json` (`phase_7_8_blocked: false`) in a dedicated
   PR that links this checklist with each box evidenced.
2. Update the corresponding assertions in `production-status-gate.yml` in the
   **same** PR, so the gate enforces the new intended state rather than the
   diagnostic lock.
3. Get maintainer sign-off. The flip is a one-way door for the project's
   operating posture; treat it like a release cut.
