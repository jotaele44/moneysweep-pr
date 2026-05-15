# archive/

Preserved modules from completed pipeline phases.
All code is git-history safe — nothing is permanently deleted.
Modules here are inert: not imported by active code, not referenced in CI.

## run_wrappers_r4/

27 thin wrapper scripts from the R4 backfill-orchestration phase (r47–r49z series).
Phase completed when R5 locked 14/14 sources. Each wrapper was a 30–574 line
shim around a single `contract_sweeper.pipeline.*` function.

Also contains 3 stub test files that imported from the co-archived wrappers
(each had ≤2 test functions covering R4-only logic).

Two wrappers remain in scripts/ (not archived here):
  scripts/run_production_status_gate.py       — wired in .github/workflows/production-status-gate.yml
  scripts/run_repo_quality_audit_r49z_b.py    — wired in .github/workflows/production-status-gate.yml

Those will move when production-status-gate.yml is updated.
