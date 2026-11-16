# Blockers and unblock plan — moneysweep-pr (2026-09-28)

**Audit date:** 2026-09-28 · **`main` at audit:** `2a76aa0` (branch-protected) · **Production status:** `NON_PRODUCTION_DIAGNOSTIC`, pause lock active

**Post-audit update (2026-09-28 20:35Z):** the record_cell_binding v0.2 series was pushed straight to `main` after the audit. The Cell_Set PR #623 now conflicts with `main` and is superseded (X-05).

This document lists every blocker that the repository, its CI, and its GitHub issues and pull requests recorded as of the audit date, then gives an ordered plan to clear them. It changes no code, gate, ledger, or status file.

Cross-repository blockers (IDs `X-nn`) are described in full in
`jotaele44/thehub-pr` → `docs/BLOCKERS_AND_UNBLOCK_PLAN_2026-09-28.md`.

## How this inventory was built

Sources checked:

- all 46 open issues and all 11 open pull requests;
- CI on `main`, for push and scheduled runs;
- per-PR check results from the thehub federation completion-gate artifact (run `36326861596`, 2026-09-27 14:42Z);
- `docs/unfinished_implementation_ledger.v1.json`, reconciled against PR history;
- `STATUS.md`, `HANDOFF.md`, `AUDIT.md`, `RECOMMENDATIONS.md`;
- `docs/CERTIFICATION_STATUS.md`, `docs/RESUMPTION_CHECKLIST.md`, `docs/BLOCKED_PHASES_AND_UNFREEZE_RULES.md`, `docs/ROAD_TO_100_NORMALIZED.md`, `docs/GAP_ANALYSIS_AND_OPTIMIZATION_2026-09.md`;
- `reports/current_status.json` and `data/review_queue/*blocker*.csv`;
- the branch list and branch protection.

Limits are listed at the end.

## Summary

Each blocker is counted once, under its primary type.

| Type | Meaning | Count |
|---|---|---:|
| CI | Automation that is red now, or will expire | 2 |
| CRED | Missing secret or credential | 1 |
| DATA | Needs operator or external data | 4 |
| GATE | A fail-closed gate is not passing | 2 |
| GOV | Needs a maintainer decision | 3 |
| PR | Stuck pull requests | 1 group (11 PRs) |
| IMPL | Recorded implementation gaps | 1 |
| STALE | Resolved, but the tracker or doc still says blocked | 1 |
| **Total** | | **15** |

## Blocker inventory

| ID | Blocker | Type | Evidence | Owner | Unblock step | Exit criterion |
|---|---|---|---|---|---|---|
| MS-01 | `Source update — weekly` crashes before completing | CI | Run `35625880436` fails with `IsADirectoryError: data/raw/HigherGov` in `moneysweep/update_controller/validation.py` `snapshot_output()` (lines 49–61). The only directory-valued expected output is `registries/source_registry.yaml:98` (`highergov_supplemental`, weekly). The exception escapes `cli.py:297` (`future.result()`) and aborts the whole cadence. The next weekly run (2026-09-28 ~16:30Z) will fail again. | Agent/maintainer | Snapshot directories as a deterministic sorted manifest hash, or declare a manifest file as the output. Isolate per-source exceptions in `execute_selected` so one source cannot abort a cadence. Add a regression test. | Weekly cadence completes green |
| MS-02 | API-key secrets empty in Actions | CRED | The cadence env shows `CENSUS_API_KEY`, `EIA_API_KEY`, `FAC_API_KEY`, `FRED_API_KEY`, `OPENSTATES_API_KEY`, `FINANCIALDATA_API_KEY` and `FINANCIALDATA_LICENSE_APPROVED` empty. Only `FEC`, `HIGHERGOV` and `SAM` are set. | Operator | Provision the secrets (and the license approval) in repository settings | Keyed sources materialize in scheduled runs |
| MS-03 | Required sources at 10/14; the coverage gate needs ≥ 0.85. Missing: COR3 repository-side ingest backed by a receipt (the workbook is already validated on the operator host); HUD DRGR authorized activities and projects exports; DOJ cabilderos structured export; OCPR/PRASA-filtered contracts; CMS provider-level input; authoritative export-receipt manifest | DATA | `docs/CERTIFICATION_STATUS.md` (without the portal sources the reachable ceiling is 9/14). Epic #271, #257, ledger MSW-001..004, `reports/current_status.json` `open_work` | Operator | Supply the missing items into the dropzone with receipts, then ingest and rerun the 151-source audit | Required coverage ≥ 12/14 and the audit is regenerated |
| MS-04 | `usaspending_prime` all-awards master cannot be built | DATA | `scripts/build_unified_master.py` needs about 15 upstream masters. `data/review_queue/sources_still_blocked_r4_9h2.csv` lists 16 inputs (9 `manual_file_required`, 7 `physical_validated_file_missing`). | Operator | Supply or derive the upstream masters | `usaspending_prime` fully materialized |
| MS-05 | Production lock holds by design | GATE | `data/review_queue/production_blockers.csv`: `data_layers_populated` 3 (needs ≥ 8), `unique_entities` 18 (needs ≥ 100), fixture detected. R4.9→R10 phases blocked (`downstream_phase_blockers_r4_9z.csv`). 8-item `docs/RESUMPTION_CHECKLIST.md`. | Maintainer (release cut) | Clears only after MS-03, MS-04 and MS-06 | Checklist items 1–8 evidenced |
| MS-06 | Almost no sources are fresh | GATE/DATA | Weekly freshness output: 167 sources, 156 `NEVER_MATERIALIZED`, 5 `BLOCKED_MANUAL_INPUT`, 1 `DISABLED`, 5 `TERMINAL`. #259 (56 automatable sources never run) and #257 are labelled `blocked:sandbox`, but they can now run in GitHub Actions. | Agent + operator | After MS-01 and MS-02, run the cadences, then relabel #257 and #259 | Freshness counts improve with receipts |
| MS-07 | JP macro workbooks needed for VECTOR_C | DATA | #595: sector allocation 0 of 41,664.1 classified; company and ownership allocation `BLOCKED_UPSTREAM` | Operator/agent with network | Acquire and byte-freeze the three 2025 workbooks per the issue's acquisition contract | #595 closure gate: `PASS` or formally `BLOCKED_PUBLIC_SOURCE_EXHAUSTED` |
| MS-08 | Contradictory provenance claims for 4 sources | GOV | #554: materialization claims from #541 were reverted | Maintainer | Decide whether the 2026-09-01 re-materialization was real (then re-derive `staging_masters.json` with real hashes and regenerate the chain) or discard it | Decision recorded; #554 closed |
| MS-09 | SEC ownership workflows depend on an expiring artifact | CI (time bomb) | #550: `SNAPSHOT_ARTIFACT_ID: "9598537414"` is hard-coded in `.github/workflows/sec-ownership-golden-data-audit.yml:44` and `sec-ownership-issuer-certification.yml:62,91`. Retention is 90 days; by artifact-ID sequence the artifact dates from about late August, so it expires about late November 2026. Verify the exact date with the artifacts API. | Agent/maintainer | Resolve the latest successful snapshot artifact dynamically, or document regeneration. Tag `313def60` so the cited audit anchor stays reachable. It exists on GitHub but not in `main`'s ancestry. | No hard-coded artifact ID; anchor tagged |
| MS-10 | Control issue no longer matches reality | GOV/STALE | #526 requires PR #520 to be OPEN + DRAFT, but #520 was closed on 2026-09-03. The archive pointer `archive/pr-520-certified-draft-5646ad6` is intact. | Maintainer | Reclassify the control to use the archive branch as the sole certification identity, or close it | #526 reflects #520's closed state |
| MS-11 | Open PRs are red, stacked or waiting | PR | See the next table | Agent + maintainer | Per-PR actions below | No red or stacked PRs left |
| MS-12 | The declared source of truth is stale | STALE | `reports/current_status.json`: generated 2026-08-20, `evidence_snapshot_state: STALE_NOT_RECERTIFIED`, still lists #452 as an open draft (merged 2026-08-11). `STATUS.md` test baseline is 2026-07-26; the measured baseline on 09-20 was 2,947 passed, 54.65%. `docs/ROAD_TO_100_NORMALIZED.md` is dated 2026-07-30. | Agent | Re-emit from measurement (GAP_ANALYSIS D2/D3) | Status files match current `main` |
| MS-13 | Open P1/P2 items from the September gap analysis | IMPL | `docs/GAP_ANALYSIS_AND_OPTIMIZATION_2026-09.md`: A5 make GUI parity a required status check; B2 tests for `desktop/secrets.py` (0%) and `server/backend/main.py` (35%); C2 BaseDownloader migration (63 non-adopters); B4 decompose `run_all_legacy.py` (2,073 LOC); C3 ruff ratchet; C4 untrack `reports/local_analysis/`; D4 federation identity provider for the case manager | Agent/maintainer | Work in the document's priority order | Each item closed on `main` |
| MS-14 | Pending sequencing from STATUS.md: archive PR-1 needs the G1 run-wrapper proof plus Architect approval; HigherGov archive needs a consumer refactor; PR2.5/PR2.6 reconciliation before PR3 dedup; source-intake taxonomy | GOV/IMPL | `STATUS.md` "Current Blockers" | Maintainer | Sequence per STATUS "Next native vectors" | Each vector closed |
| MS-15 | Ingestion backlog | DATA | Issues #272–#307 (36 issues, including the municipal sub-epic #303), each waiting on network, keys or manual exports | Operator | Triage once MS-01 and MS-02 land; close anything the cadences materialize | Backlog triaged |

### Open pull requests (MS-11)

| PR | State | Action |
|---|---|---|
| #623 Cell_Set uncertainty contract | Conflicts with `main` since the post-audit v0.2 series, which already carries the contract in `federation/spatial/registry_version.json` | Confirm v0.2 covers it, then close as superseded (X-05) |
| #612 credential-name registry | RED: CodeQL, pytest, ruff, pre-commit, test (3.13) | Fix or close |
| #602 v4.0.0-rc1 census (draft) | RED: 9 checks | Fix or close |
| #619 main → `agent/max-production-certification-v2` | STACKED; 19 cancelled checks | Decide whether v2 is superseded by v3 (#620). If so, close #619 and archive the v2 branch |
| #620 MAX certification v3 (draft) | 2 cancelled materialize jobs; 4 unresolved review threads | Resolve the threads, then rerun |
| #622 public-finance certification skill (draft) | Green | Review |
| #604 npm minor/patch group | RED: pytest, test (3.13) | Regenerate the prebuilt dashboard, rerun |
| #605 eslint 10 | RED: 11 checks | Migrate the flat config, or ignore the major (X-02) |
| #606 vitest 5 | RED: pytest, test (3.13) | Migrate, or ignore the major |
| #607 python minor/patch group | RED: lock-sync | Regenerate `requirements.lock` |
| #608 actions minor/patch group | RED: Federation template drift | Land the bump in thehub `federation-templates`, re-render, close this PR |

## Unblock plan

### P1 — executable now (no external input)
1. **MS-01:** fix the directory snapshot and isolate per-source failures, with a regression test, before the next weekly run.
2. **MS-09:** stop depending on the hard-coded artifact ID; tag `313def60`.
3. **MS-11:** triage the PRs. Close or fix #612 and #602; regenerate the lock for #607; route #608 through thehub templates.
4. **MS-12:** regenerate `reports/current_status.json`, `STATUS.md` and the road-to-100 document from measurement.
5. Close #551 with evidence: both failures it reported are green on `main`, and the `ingest_prasa_transition_contracts` capability is registered in `.federation/gui-capabilities.json`.

### P2 — operator inputs
1. **MS-02:** provision the six missing API keys and the license approval.
2. **MS-03, MS-04:** supply the required exports and upstream masters with receipts.
3. **MS-07:** acquire the JP workbooks.
4. **MS-06, MS-15:** after P2.1, run the source-update cadences and relabel the `blocked:sandbox` issues.

### P3 — maintainer decisions
1. **MS-08:** decide the #554 provenance question.
2. **MS-10:** reclassify control #526.
3. **MS-11:** dispose of the MAX v2/v3 lineage (#619 and #620).
4. **MS-14:** approve archive PR-1 (G1) and the PR2.5/2.6 → PR3 order.

### P4 — longer horizon
1. **MS-13:** gap-analysis items A5, B2, C2, B4, C3, C4, D4.
2. **MS-05:** the production release cut, following the 8-item resumption checklist.

## Ledger reconciliation (`docs/unfinished_implementation_ledger.v1.json`, dated 2026-08-04)

| Ledger ID | Ledger state | State on 2026-09-28 |
|---|---|---|
| MSW-001..004 | operator_input | Still blocked → MS-03 |
| MSW-005 | open_pr (#453) | #453 merged 2026-08-09. OCPR data is still missing → MS-03 |
| MSW-006 | operator_run | #451 merged 2026-08-11. Strict FEC closure (14/14, `strict_ok`) still needs verification |
| MSW-007 | main_gap | Resolved: `entity_master.csv` lineage confirmed (`reports/current_status.json`) |
| MSW-008 | rescue_pr (#459) | Resolved: #459 closed unmerged 2026-08-11 |
| MSW-009 | open_pr (#457, #458) | Resolved: both merged |
| MSW-010 | governance_gate | Still gated → MS-05 |

## Stale trackers and hygiene
- #551: resolved on `main`; close with evidence.
- #222 (blob purge): deliberately deferred; keep open.
- #269 (branch cleanup): 39 branches on origin, 18 of them from agents or automation.
- Fleet `AUDIT.md` gap: the frontend is a single Dashboard page with no routing.

## Federation-wide blockers that affect this repo
- X-01: the completion gate is red daily.
- X-02: dependabot backlog and template drift.
- X-05: the Cell_Set PR set, now superseded by v0.2 on `main`.
- X-07: stale normalized ledgers.

See the thehub document for details.

## Not verifiable with the access used for this audit
- Code-scanning and Dependabot security-alert inventories.
- Which Actions secrets exist (inferred only from workflow logs).
- Operator-host data under gitignored `data/**`.
