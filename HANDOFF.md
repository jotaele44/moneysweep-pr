# Handoff — moneysweep-pr

**Date:** 2026-05-15  
**Outgoing operator:** jotaele44 (original/legacy account)  
**Incoming operator:** Edu-enabled GitHub account  
**Transfer method:** Repo-preserving (clone + collaborator invite, not fork; no history loss)  
**Status:** Handoff files generated; awaiting Edu-account clone + test validation before any ownership change

---

## What This Repository Is

moneysweep-pr is a data pipeline for collecting, normalizing, linking, and analyzing Puerto Rico government procurement and federal spending data. It ingests 80+ public and semi-public data sources, resolves entities, builds a unified awards master, and produces network/influence graphs and compliance reports.

The production rebuild is currently **paused** (`NON_PRODUCTION_DIAGNOSTIC`) pending delivery of 21 missing source files. The pipeline architecture, validation gates, and test suite are fully functional.

---

## Repository Structure

```
moneysweep-pr/
├── moneysweep/          # Core Python package
│   ├── pipeline/              # Orchestration & backfill modules (43 files)
│   ├── runtime/               # Shared utilities: hashing, registries, gates (9 files)
│   └── validation/            # Validation gate logic (8 files)
├── scripts/                   # 165 executable scripts
│   ├── download_*.py          # 74 per-source downloaders
│   ├── ingest_*.py            # 11 ingest/staging transformers
│   ├── run_*.py               # 29 thin CLI wrappers (MERGE candidate)
│   ├── validate_*.py          # Coverage/integrity validators
│   ├── analyze_*.py           # Analysis & graph builders
│   └── config.py              # Central config (121 inbound imports — critical)
├── tests/                     # 100 test files; 594 passing
├── docs/                      # Architecture, policy, runbooks
├── reports/                   # Generated status and inventory CSVs
├── registries/                # source_registry.json, schema_registry.json
├── data/                      # Gitignored data files (structure tracked via .gitkeep)
├── run_all.py                 # Main pipeline orchestrator
├── SETUP.md                   # ← Start here for new operators
├── STATUS.md                  # Current project status
└── .env.example               # API key template (copy to .env)
```

---

## Handoff Readiness Checklist

| Item | Status |
|------|--------|
| Active branches identified | ✅ `main`, `claude/module-reduction-cleanup-ogfpf` |
| Open issues reviewed | ✅ #69 (module reduction), #70 (this handoff) |
| Open PRs | ✅ None open |
| Setup command documented | ✅ See SETUP.md |
| Test command documented | ✅ `python3 -m pytest tests/ -q` |
| Secrets removed / confirmed absent | ✅ 0 findings (551 files scanned) |
| `.env.example` present | ✅ |
| Large data files classified | ✅ All gitignored; data/ structure preserved via .gitkeep |
| `reports/current_status.json` exists | ✅ |
| `next_command` defined | ✅ |

---

## Incoming Operator — Getting Started

1. **Read** `SETUP.md` for clone and installation instructions.
2. **Read** `STATUS.md` for current pipeline state.
3. **Read** `docs/OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md` for what must happen before the production rebuild can resume.
4. **Do not** run download retries, ingest rows, or stage production inputs until source blockers are resolved (see `reports/gap_analysis_report.csv`).

---

## Preferred End-State for Account Governance

| Role | Account |
|------|---------|
| Legacy owner / backup admin | jotaele44 (current account) |
| Active operator | Edu-enabled GitHub account |
| Future final owner | GitHub Organization (TBD) |

**Do not transfer ownership until:** Edu account has successfully cloned the repo, installed dependencies, and run `pytest` with all tests passing.

---

## Key Files for Incoming Operator

| File | Purpose |
|------|---------|
| `SETUP.md` | Install + run instructions |
| `STATUS.md` | Current state, blockers, next actions |
| `reports/current_status.json` | Machine-readable project state |
| `reports/gap_analysis_report.csv` | Which sources are missing and why |
| `reports/source_registry_status.csv` | All 82 registered sources with pipeline status |
| `docs/MODULE_REDUCTION_PLAN.md` | Module consolidation roadmap (issue #69) |
| `docs/OPERATOR_NEXT_ACTIONS_AFTER_R4_9Z.md` | Step-by-step unfreeze instructions |
| `docs/SOURCE_RECOVERY_RUNBOOK.md` | Full source recovery procedures |
| `docs/SECRET_HANDLING_POLICY.md` | How API keys must be managed |
| `.env.example` | API key template |
