# Project Status — Contract-Sweeper

**Date:** 2026-05-18  
**Branch:** `main`  
**Active vector:** `NATIVE_EXECUTION_MODE`  
**Production status:** `NON_PRODUCTION_DIAGNOSTIC`  
**Latest test baseline:** 481 passed · 1 skipped · 0 failed after PR-D archive exclusion

---

## Execution Mode Update

Handoff mode is retired. The repository continues under native execution using staged pull requests from fresh `main`.

Historical handoff artifacts remain for auditability, but they no longer define the active operating mode.

Live control files:

- `reports/current_status.json`
- `docs/MODULE_CONSOLIDATION_SCOPE.md`
- `reports/module_inventory.csv`
- `reports/source_registry_status.csv`

---

## Current Native Execution State

| Area | Status | Notes |
|------|--------|-------|
| Handoff artifacts | Historical | Preserved, not deleted |
| Edu clone validation | Complete | 594 passed · 4 skipped at transfer gate |
| PR #73 scope plan | Merged | `docs/MODULE_CONSOLIDATION_SCOPE.md` controls staged reduction |
| PR #74 archive root | Merged | `archive/r4_legacy/.gitkeep` created only |
| PR #75 political crossref merge | Merged | FEC + LDA analyzer merge landed on `main` |
| PR-D expansion downloader archive | Merged | Archive excluded from pytest via `norecursedirs` |
| G1 run-wrapper proof | Pending | Required before PR-1 file movement |
| Source intake taxonomy | Pending | Uploaded contract/lobbying/PRASA/DCAA files require registry review |

---

## Completed Baseline

| Milestone | Notes |
|-----------|-------|
| R5 gate-closure chain | Validation gates passed at baseline |
| EMMA municipal bonds corpus | PR #68 merged |
| Module inventory | `reports/module_inventory.csv` |
| Module reduction plan | `docs/MODULE_REDUCTION_PLAN.md` |
| Staged consolidation scope | `docs/MODULE_CONSOLIDATION_SCOPE.md` merged via PR #73 |
| Archive root setup | `archive/r4_legacy/.gitkeep` merged via PR #74 |
| Political crossref merge | PR #75 merged |
| Expansion downloader archive | PR-D / #76 merged |
| Secrets audit | Clean at latest baseline |

---

## Current Blockers

| Blocker | Required action |
|---------|-----------------|
| Production master rebuild | Deliver and validate source inputs before promotion |
| Archive PR-1 | Complete G1 run-wrapper candidate proof and Architect approval |
| HigherGov archive/deletion | Consumer refactor must remove live references first |
| PR3 dedup/entity integration | Reconcile PR2.5/PR2.6 branch against latest `main` first |
| Source intake | Classify uploaded source files before ingestion |

---

## Triage Decisions

| Issue | Title | Category | Rationale |
|-------|-------|----------|-----------|
| #271 + children (#272–#307) | Ingestion epic — 100% coverage roadmap | `blocked:sandbox` | Requires live network egress, API keys, and operator file drops unavailable in the current NON_PRODUCTION_DIAGNOSTIC sandbox |
| #257 | Materialize 14 required sources | `blocked:sandbox` | Same sandbox constraint; key-gated and manual-export waves cannot run |
| #259 | Run 56 automatable-but-unrun sources | `blocked:sandbox` | Same sandbox constraint; producer scripts need live network egress |
| #222 | Purge large blobs from git history | Deliberate deferral | Working-tree cost is modest (~12 MB); .gitignore deny-all prevents accumulation; defer until stable merge cadence |
| #87 | Federal tier-0 fetchers (salvage) | Deliberate deferral | Revisit under source-intake batches 151–180 after materialization spine and manual-intake backlog clear |

---

## Next Native Vectors

Choose one vector at a time:

1. `G1_RUN_WRAPPER_CANDIDATE_PROOF` — create evidence-only candidate proof; no file movement.
2. `SOURCE_INTAKE_TAXONOMY` — classify uploaded PR contract, lobbying, PRASA, and contractor-reference datasets.
3. `PR2_5_PR2_6_RECONCILIATION` — reconcile entity-gate branch against latest `main` before PR3 deduplication.

---

## Operating Rules

- Start every repo task from fresh `main` unless a PR branch is already under review.
- Do not combine module consolidation with source ingestion.
- Do not move files without the relevant Architect gate.
- Preserve handoff artifacts as historical audit records.
- Use delta-only reporting and maintain `reports/current_status.json` as the machine-readable source of truth.

---

## What NOT To Do Right Now

- Do not reopen handoff/org-transfer flow.
- Do not delete `HANDOFF.md`.
- Do not start PR-1 without G1 approval.
- Do not ingest uploaded source files directly into production paths.
- Do not wire PR3 deduplication before PR2.5/PR2.6 reconciliation.
