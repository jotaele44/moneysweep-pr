# Contract-Sweeper — Handoff Document

**Repo:** jotaele44/contract-sweeper  
**As of:** 2026-05-15  
**Stage:** Governance-controlled (R7 active) · 639/639 tests passing

---

## What This Repo Is

A governed analytical pipeline for Puerto Rico federal contracting, disaster-recovery
spending, and political-finance data.  It acquires, normalises, and cross-references
14 registered sources to produce risk-ranked outputs that support investigative and
oversight work.

**It is not** a scraper collection.  Every output is traceable to a source row,
every gate is enforced by CI, and every signal carries an explainability field.

---

## Current State

| Dimension | Status |
|---|---|
| Source coverage | 14/14 required sources · coverage rate 1.000 (≥ 0.93) |
| CI gate | Hard-enforced (no `--allow-failed`) · exits 1 on any gate fail |
| Active branch | `claude/r7-risk-signal-engine` |
| Production branch | `main` (R5 locked) |
| Test baseline | 639 passed, 5 skipped |
| Risk signal engine | R7 v1 shipped (8 signal families, 40 unit tests) |
| Module inventory | 304 modules · 47.9% identified as archiveable |
| Handoff readiness | ~65/100 (this document is part of the improvement) |

---

## Active Work Branch

```
claude/r7-risk-signal-engine
```

Ahead of `main` by 5 commits.  Contains:
- Phase 7 risk signal engine (`contract_sweeper/runtime/risk_signals.py`)
- R7 gate module (`contract_sweeper/runtime/risk_signal_gates.py`)
- Runner script (`scripts/build_risk_signals.py`)
- 40 unit tests (`tests/test_risk_signals.py`)
- Module inventory + reduction plan (`module_inventory.csv`, `MODULE_REDUCTION_PLAN.md`)

This branch has not been merged to `main` yet.  It is the correct base for all
current development.

---

## Branch Audit

| Branch | State | Notes |
|---|---|---|
| `main` | Production | R5 locked, 14/14 gates passing |
| `claude/r7-risk-signal-engine` | Active | Current work branch — all new work goes here |
| `claude/assess-branch-status-zPGba` | Superseded | HUD DRGR gate work — merged into current branch |
| `claude/r5-ci-gate-enforcement` | Superseded | CI enforcement — merged to main |
| `claude/r5-pr6x-*` | Superseded | R5 gate closure series — all merged to main |
| `remotes/origin/codex/*` | Stale | Pre-R5 codex drafts — safe to delete |

---

## Immediate Next Steps (for incoming operator)

1. **Merge `claude/r7-risk-signal-engine` → `main`** after confirming CI passes.
2. **Run staged archival** per `MODULE_REDUCTION_PLAN.md` (PR-A through PR-E in order).
3. **Create `archive/` directory** at repo root for R4 pipeline modules.
4. **Freeze source scope** — do not add new sources during consolidation.
5. **Establish one canonical orchestration path** (see ARCHITECTURE.md).

---

## Critical Files

| File | Purpose |
|---|---|
| `registries/source_registry.yaml` | Single source of truth for all 14 registered sources |
| `registries/schema_registry.yaml` | Column schemas per source |
| `contract_sweeper/runtime/validation_gates.py` | CI-enforced gate definitions |
| `data/manifests/validation_report.json` | Last gate run result |
| `data/ci/seeds/` | Committed seed CSVs that satisfy gates in CI (no real data needed) |
| `.github/workflows/ci.yml` | CI pipeline (compile → pytest → secrets scan → gates) |
| `MODULE_REDUCTION_PLAN.md` | Staged archival plan |
| `module_inventory.csv` | Full 304-module categorisation |

---

## Known Issues / Risks

| Issue | Risk | Mitigation |
|---|---|---|
| `hud_drgr_authorized` uses seed data only | Medium | Real data requires grantee-portal login at drgr.hud.gov; see `data/staging/expansion/DOWNLOAD_INSTRUCTIONS.md` |
| 62 expansion downloaders archived but not yet removed | Low | They exist in `scripts/`; do not execute without validating against current API endpoints |
| 19 stub test files (≤2 tests each) cover archived pipeline | Low | Archive with their pipeline modules per PR-B in reduction plan |
| No canonical `main.py` / orchestration entry point | Medium | Priority once archival is complete |

---

## Contacts / Ownership

- **Repo owner:** jotaele44  
- **Current AI operator:** Claude Code (claude-sonnet-4-6)  
- **Work sessions:** See `https://claude.ai/code/` — session IDs in commit trailers

---

## How to Hand Off

1. Point the new operator to `SETUP.md` for environment bootstrap.
2. Walk through `ARCHITECTURE.md` — the data flow diagram is the fastest orientation.
3. Run `pytest -q` to confirm the baseline is still clean.
4. Run `python -m contract_sweeper.runtime.validation_gates --root .` to confirm all 14 gates pass.
5. Review `MODULE_REDUCTION_PLAN.md` before touching any files.
