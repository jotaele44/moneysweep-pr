# Issue Triage — 2026-05-20

Triage of new and unassigned issues in `jotaele44/moneysweep-pr`, plus
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
| 2 | Module consolidation PRs | Increment done; next gate human | PR-D…PR-I all merged (PR-I = `d1cb07a`); `G6` scope selection is an Architect decision |
| 3 | Promotion guard (#86) | Done (this PR) | `moneysweep/validation/promotion_guard.py` + CI |
| 4 | Governance artifact suite (#86) | Done (this PR) | `docs/PROMOTION_GUARD.md`, workflow, tests |
| 5 | Handoff documentation (#70) | Done | `HANDOFF.md`, `STATUS.md`, `SETUP.md`, `.env.example` |
| 6 | Edu-account clone validation (#70) | Done | 594 passed at transfer gate (per `current_status.json`) |
| 7 | Federal fetchers (#87) | PR-B4 done (this PR) | PR-B1/B2/B3 merged; PR-B4 wires 7 disaster/research sources; B5/B6 staged |
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
- **PR-B4 disaster/research source wiring (area 7).** Un-archived 7
  downloader modules (`download_fema`, `download_nfip`, `download_slfrf`,
  `download_haf`, `download_usace_civil`, `download_usace_permits`,
  `download_nih`) covering 7 registry sources. YAML registry repointed to
  `scripts/`, `source_registry.json` regenerated via
  `regenerate_registry_json.py`, `gap_analysis_report.*` and
  `source_registry_status.csv` regenerated via `gap_analysis_builder.py`,
  smoke suite extended with `B4_DISASTER_RESEARCH`. 24 optional sources
  remain archived for PR-B5/B6.
- **Status sync (area 2).** `reports/current_status.json` updated: PR-I
  marked merged, PR-B4 recorded, test baseline 575 passed.

## Status of the two previously-deferred areas

- **Area 2 (module consolidation, #69)** — PR-D through PR-I are all merged.
  PR-I (`d1cb07a`) archived `dominance_analysis` and `analyze_prime_sub`;
  `current_status.json` was stale and is corrected here. The remaining step,
  gate `G6`, is an Architect *scope-selection decision* for the next
  consolidation batch — a human gate, not an executable task.
- **Area 7 (federal fetchers, #87)** — PR-B4 is delivered in this PR (see
  above). PR-B5 (territorial/municipal) and PR-B6
  (bonds/entity-resolution/manual) remain in the staged program; bundling
  all of B5+B6 here would violate the "one staged batch per PR" discipline.

## Next 10 areas after this PR

1. Architect gate `G6` — select the next consolidation scope (#69).
2. PR-B5 — wire territorial/municipal sources (#87).
3. PR-B6 — wire bonds/entity-resolution/manual sources (#87).
4. Verify the 7 PR-B4 producers against live endpoints when sources unfreeze.
5. Sync the repo labels to `.github/labels.yml` (priority + area labels).
6. PR2.5/PR2.6 entity-gate branch reconciliation before PR3 dedup.
7. Source intake taxonomy for uploaded contract/lobbying/PRASA datasets.
8. Resolve HigherGov consumer refactor to unblock its archive boundary.
9. Module inventory refresh after PR-B5/B6 land.
10. Add a branch-protection rule requiring the Promotion Guard check on
    `master`.
