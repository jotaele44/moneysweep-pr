# Issue Triage — 2026-05-20

Triage of new and unassigned issues in `jotaele44/Contract-Sweeper`, plus
status of the ten follow-up areas. Open issues at triage time: #69, #70,
#86, #87. No duplicates found.

## Triaged issues

| # | Title | Category | Priority | Area | Duplicate |
|---|-------|----------|----------|------|-----------|
| #69 | MODULE_REDUCTION_ARCHITECTURE_LOCK | Improvement | Critical | architecture | No |
| #70 | HANDOFF_PREP: Edu-account takeover | Improvement | High | governance | No |
| #86 | Governance artifacts + promotion guard (salvaged #49) | Feature Request | High | governance | No |
| #87 | Federal tier-0 acquisition fetchers (salvaged #50) | Feature Request | Medium | data-ingestion | No |

## Follow-up areas — status

| # | Area | Status | Evidence |
|---|------|--------|----------|
| 1 | Module inventory (#69) | Done | `reports/module_inventory.csv` (225 modules) |
| 2 | Module consolidation PRs | In progress / gated | PR-D…PR-I merged; PR-I open; next gate `G6` |
| 3 | Promotion guard (#86) | Done (this PR) | `contract_sweeper/validation/promotion_guard.py` + CI |
| 4 | Governance artifact suite (#86) | Done (this PR) | `docs/PROMOTION_GUARD.md`, workflow, tests |
| 5 | Handoff documentation (#70) | Done | `HANDOFF.md`, `STATUS.md`, `SETUP.md`, `.env.example` |
| 6 | Edu-account clone validation (#70) | Done | 594 passed at transfer gate (per `current_status.json`) |
| 7 | Federal fetchers (#87) | Staged | PR-B1/B2/B3 merged; PR-B4…B6 pending |
| 8 | Source registry audit | Done | `reports/source_registry_status.csv` (82 sources) |
| 9 | Gap analysis report | Done | `reports/gap_analysis_report.csv` |
| 10 | Label hygiene + issue templates | Done (this PR) | `.github/ISSUE_TEMPLATE/`, `.github/labels.yml` |

## Delivered in this PR

- **Promotion guard (#86, areas 3 & 4).** `promotion_guard.py` blocks
  promotion of a build to `master` when a validated production tier is
  claimed without evidence (pause lock released, tests GREEN, clean secrets
  audit, production-status gate passing with zero blockers). Diagnostic
  development is unaffected. Wired into CI via `promotion-guard.yml`;
  covered by 13 tests in `tests/test_promotion_guard.py`.
- **Issue templates (area 10).** `bug_report`, `feature_request`,
  `improvement`, `question` forms plus `config.yml`. Issues #86 and #87 were
  filed without labels — these templates apply category labels at creation.
- **Label set (area 10).** `.github/labels.yml` defines canonical category,
  priority, and area labels for consistent triage.

## Open items not in this PR (scoped, not regressed)

- **#69 / area 2** — module consolidation file moves are behind Architect
  gate `G6`. No file moves were performed; this PR adds only new files.
- **#87 / area 7** — federal source wiring continues under the staged
  PR-B4…B6 program. `current_status.json` `next_command` is
  `OPEN_PR_B4_WIRE_DISASTER_RESEARCH_SOURCES`. Per the operating rule "do
  not combine module consolidation with source ingestion," that work is
  kept as a separate PR rather than bundled here.

## Next 10 areas after this PR

1. Architect gate `G6` — select post-PR-I consolidation scope (#69).
2. PR-B4 — wire disaster/research downloader sources (#87).
3. PR-B5 — wire territorial/municipal sources (#87).
4. PR-B6 — wire bonds/entity-resolution/manual sources (#87).
5. Sync the repo labels to `.github/labels.yml` (priority + area labels).
6. PR2.5/PR2.6 entity-gate branch reconciliation before PR3 dedup.
7. Source intake taxonomy for uploaded contract/lobbying/PRASA datasets.
8. Resolve HigherGov consumer refactor to unblock its archive boundary.
9. Refresh `reports/current_status.json` once PR-I and B4 land.
10. Add a branch-protection rule requiring the Promotion Guard check on
    `master`.
