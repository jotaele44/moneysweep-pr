# Project Status — moneysweep-pr

**Date:** 2026-11-15  
**Branch:** `main`  
**Active vector:** `REQUIRED_SOURCE_AND_OPERATOR_EVIDENCE_CLOSURE`  
**Production status:** `NON_PRODUCTION_DIAGNOSTIC`  
**Latest test baseline:** 3194 passed · 10 skipped · 0 failed · 55.20% coverage (gate: 44%)

> Measured 2026-11-15 by `python -m pytest tests/ -q` on **Python 3.13.18** (the version
> `.github/workflows/tests.yml` pins), using the install from `requirements-dev.txt` plus
> `jsonschema` and `server/backend/requirements.txt`, on `main` at `08e1bb2` plus the
> weekly-cadence fix. Re-measure this row whenever you edit it; do not carry it forward by
> hand.

## Measured state (2026-11-15)

| Measure | Value | Source |
|---|---|---|
| Registered sources | 167 (119 automatable and structurally ready, 48 queued or excluded) | `reports/materialization_readiness.json` |
| Fully / partially / not materialized | 20 / 3 / 144 | `reports/source_registry_status.csv` |
| Required sources fully materialized | 12 of 16 | `reports/source_registry_status.csv` |
| Sources with a recorded scheduled success | 0 of 144 tracked | `reports/source_freshness.csv` |
| Production blockers | 3 (data layers 3 of ≥ 8; entities 18 of ≥ 100; fixture data detected) | `data/exports/production_status.json` (2026-07-28) |

The current audit and the ordered plan for closing these gaps is
[`docs/AUDIT_AND_OPTIMIZATION_STRATEGY_2026-11-13.md`](docs/AUDIT_AND_OPTIMIZATION_STRATEGY_2026-11-13.md).
`reports/current_status.json` is a frozen Wave 0 certification record (2026-07-30 evidence,
151-source denominator); it is not a live status and must not be read as one.

> **Everything below this line is the 2026-07-26 status, kept for the record.** Its
> blockers, triage labels and next vectors predate the measurements above; where they
> disagree, the table above and the strategy document win.

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
