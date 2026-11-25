# moneysweep-pr — audit against the desired outcome, and optimization strategy

**Audit date:** 2026-11-13 to 2026-11-15 · **Head audited:** `main` at `52cc34b`, re-checked at `08e1bb2`
**Method:** read the repository's own goal and status documents, measured the code and
committed reports, ran the full test suite, and read open pull requests, open issues and
recent workflow runs through the GitHub API. Data under gitignored `data/**` on an
operator machine, and which Actions secrets exist, were not visible.

## Desired outcome

From `docs/PRODUCTION_GATES.md`, `docs/RESUMPTION_CHECKLIST.md`, `docs/ROAD_TO_100.md` and
the README operating contract: a production-certified public-money master dataset for
Puerto Rico. That means the top rung, `PRODUCTION_VALIDATED`, of an eight-rung gate
ladder: every required source materialized with receipts, sources refreshed on their
cadence, the R5 validation gates passing on real data, and the export validated by the hub
(`thehub-pr`).

## Current state against that outcome

| Area | Desired | Measured | Gap |
|---|---|---|---|
| Production gate | `PRODUCTION_VALIDATED` | `NON_PRODUCTION_DIAGNOSTIC`, rung 1 of 8 | `data/exports/production_status.json` (2026-07-28): 3 data layers of ≥ 8, 18 entities of ≥ 100, fixture data detected |
| Required sources | 16 of 16 fully materialized | 12 of 16 | `hud_drgr_authorized`, `campaign_finance_entities`, `campaign_finance_materialization_gate` not materialized; `usaspending_prime`, `prasa` partial |
| All sources | 119 automatable sources materialized | 20 of 167 fully, 3 partially, 144 not | 12 automatable sources need API keys |
| Freshness | Sources refreshed on cadence | 0 of 144 tracked sources has a recorded success | The weekly cadence has not completed a run |
| Scheduled CI | Green | `Source update — weekly` failed again on 2026-11-09 | `IsADirectoryError` on `data/raw/HigherGov/`; reported 2026-09-28; fix PR #661 in draft since 2026-10-12 |
| Push and PR CI | Green | Green: 21 workflows on the latest `main`; docs-sync 0 violations | None |
| Tests | Green, above the gate | 3194 passed, 10 skipped, 55.20% coverage (gate 44%) | None; the gate could be raised |
| SEC certification | Durable frozen snapshot | Both workflows download Actions artifact `9598537414`, which expires 2026-11-24 08:14 UTC | Issue #550, open since 2026-09-02 |
| Status documents | One measured source of truth | `STATUS.md` dated 07-26; four test baselines across docs (594, 2018, 2394, 2947); three source counts (151, 164, 167) | `reports/current_status.json` is named "current" but is a frozen Wave 0 record whose tests pin PR #452 as an open draft; it merged 2026-08-11 |
| Work in progress | Small and moving | 38 open PRs, 24 of them drafts; 49 open issues; 119 remote branches | Fixes wait behind new features |
| Code structure | Logic in the importable package | `scripts/` 99k lines against `moneysweep/` 36k; `BaseDownloader` has no adopters among 104 download and scrape scripts; `run_all_legacy.py` is 2,073 lines; ruff selects only `E4`, `E7`, `E9`, `F` | Recommendations from May and September remain open |
| GUI | Diagnostic only; the hub is the product (ADR 0001) | One page, about 24 components | Acceptable by design |

## Central finding

Engineering hygiene is strong and data is the binding constraint. The repository's own
score (61.7 of 100, 2026-08-04) is held down by data materialization (45) and operator
verification (35), which together carry 30% of the weight. Since late September the merges
have gone to new verticals: the spatial grid V2, the entity-network kernel, leaderboards,
financial classification and the ECPAF pin. Over the same weeks the one job that
materializes data on a schedule stayed red, and its fix stayed in draft.
`docs/ROAD_TO_100.md` already says new analytical verticals do not outrank required-source
closure. The strategy below is mostly about following that rule.

## Strategy, in order of leverage

### 1. Unblock the data loop (days)

- Fix the weekly cadence crash and stop one source from aborting a cadence. **Done in the
  change that adds this document:** directory outputs are hashed as a sorted manifest
  (ported from PR #661), and a controller-side exception is recorded against its own
  source.
- Make the SEC snapshot durable. **Prepared in the same change:** after merge, dispatch
  `SEC Ownership Snapshot Preserve` once **before 2026-11-24**. It copies the artifact,
  verified against its SHA-256, to release `evidence-sec13f-bpop-8q-v1`. If the date
  passes first, the snapshot has to be re-acquired and every pinned hash re-certified.
- Operator: provision the secrets the cadences need. The September audit found `CENSUS`,
  `EIA`, `FAC`, `FRED`, `OPENSTATES`, `FINANCIALDATA` (with its license approval) and
  `PROPUBLICA` keys missing from Actions.
- Then let the weekly, monthly, quarterly and yearly cadences run. This is the cheapest
  available movement on the 144 unmaterialized sources, and it is what issues #259 and
  #257 ask for. Both still carry the `blocked:sandbox` label, which no longer applies now
  that the cadences run in Actions.

### 2. Make status measured, not written (days)

- Generate one status file from measurement in CI (test counts, registry counts,
  materialization counts, freshness) and have `STATUS.md` and the README quote it.
- Rename or clearly label `reports/current_status.json` as the Wave 0 record it is.
  `scripts/check_status_freshness.py` requires its `main_sha` to equal `HEAD`, which a
  committed file cannot satisfy, and `tests/test_wave0_status_reconciliation.py` pins the
  old SHA; the checker is not run in CI. Decide which of the two is the contract.
- Mark `HANDOFF.md`, `docs/unfinished_implementation_ledger.v1.json`,
  `reports/current_blockers.md` (2026-06-14) and `reports/next_actions.md` as historical,
  or delete them. Three ledger items (MSW-007, -008, -009) were resolved by September.

### 3. Cut work in progress (one to two weeks, maintainer decisions)

Suggested dispositions; none were carried out by this audit.

| Pull requests | Suggested action |
|---|---|
| #661 weekly HigherGov snapshot | Close as superseded once this change merges |
| #696 Financial Classification V1 | Close; #712 rebased it and merged |
| #676 DuckDB Arrow API | Close; `ba1d81d` merged the same fix |
| #710 comparator parity contract | Close if #711 (merged) covers it |
| #684, #687, #689, #672 grid V2 authority and profile API | Four overlapping PRs; pick one line and close the rest |
| #690, #694, #697, #701, #704, #681, #686, #677, #673 PR-registry audit drafts | One stacked series; merge in order or consolidate into one |
| #602, #612, #620, #622, #631, #639, #644 | Older than six weeks; fix and merge, or close with a note |
| #645, #655 Copilot drafts | Review or close |
| #691, #706, #707 dependabot groups | Regenerate `requirements.lock` and the prebuilt dashboard; route the Actions bump through the hub templates |
| #605 eslint 10, #606 vitest 5 | Migrate, or tell dependabot to ignore the major |

| Issues | Suggested action |
|---|---|
| #551 | Close with evidence; both gates are green on `main` |
| #550 | Close after the snapshot is preserved |
| #526 | Reclassify or close; PR #520 closed on 2026-09-03 |
| #554 | Decide whether the 2026-09-01 re-materialization was real |
| #272–#307 (36 ingestion issues, untouched since June) | Re-triage after the cadences run; close what they materialize |
| #269 | Prune merged branches; 119 exist on the remote |

Adopt two working rules: no new vertical PR while a scheduled workflow is red, and a draft
older than 30 days is merged or closed.

### 4. Close the required sources (operator, weeks)

- `hud_drgr_authorized`: authorized activities and projects exports.
- `prasa`: the filtered official contract export.
- `usaspending_prime`: the upstream masters `scripts/build_unified_master.py` needs
  (`data/review_queue/sources_still_blocked_r4_9h2.csv` lists them).
- The two campaign-finance sources: run the live materialization workflow to its gate.
- Then re-run the full materialization audit on the current 167-source denominator (the
  certified one is still 151) and recompute `production_status.json` on real data.

### 5. Structural consolidation (after 1–4)

- `BaseDownloader`: adopt it in the download scripts or delete it. It has tests and no
  users.
- Decompose `run_all_legacy.py` and bring it into type and coverage scope.
- `git rm --cached -r reports/local_analysis/` (152 files that `.gitignore` already
  excludes).
- Advance the ruff ratchet: `I001` and `RUF100` first.
- Act on the 60 modules `reports/module_inventory.csv` marks as duplicates of a sibling.
- Raise the coverage gate from 44% toward the measured 55%.

### 6. Climb one rung at a time

Aim next at `PARTIAL_AVAILABLE_SOURCE_COVERAGE` with evidence, then
`COMPLETE_AVAILABLE_SOURCE_COVERAGE`. Aiming straight at production keeps every
intermediate gain invisible in the status.

## Who does what

| Owner | Action | By |
|---|---|---|
| Maintainer | Merge the change carrying this document, then dispatch `SEC Ownership Snapshot Preserve` | 2026-11-24 |
| Operator | Provision the missing API keys in Actions | Before the next weekly run |
| Maintainer | PR and issue dispositions in section 3 | Two weeks |
| Operator | Required-source exports in section 4 | As available |
| Agent or maintainer | Generated status file (section 2) | After section 1 |
| Agent or maintainer | Structural work (section 5) | After sections 1–4 |

## Not verified

- Whether the weekly cadence goes green: it can only be confirmed by its next scheduled
  run after merge. Other sources may fail for their own reasons; they will now be recorded
  individually instead of aborting the run.
- The snapshot restore action and preserve workflow have passed static validation only.
  They cannot run before they are on `main`.
- Which Actions secrets exist today; the list above comes from the September audit.
