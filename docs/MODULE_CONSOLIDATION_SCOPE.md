# Module Consolidation Scope Plan

**Date:** 2026-05-16
**Branch:** `claude/module-consolidation-scope-plan`
**Active vector:** MODULE_REDUCTION_ARCHITECTURE_LOCK
**Status:** Scope-only — no source files moved, merged, or deleted in this PR.

Upstream artifacts (already on `main`):
- `reports/module_inventory.csv` (225 rows)
- `docs/MODULE_REDUCTION_PLAN.md` (categorized targets)
- `reports/current_status.json`

This document defines the **execution scope and gate sequence** for the staged reduction PR series that Architect conditionally approved in Issue #69 (comment 4462859278). It does not authorize file movement; each numbered PR below requires its own Architect approval gate.

---

## 1. Architect-imposed invariants

These bind every PR in the sequence:

1. **Archive-only.** No logic rewrites inside the same PR as a file move.
2. **Destination.** All archived files land in `archive/r4_legacy/<original-relative-path>`. No outright deletions, with one named exception (see §3 PR-0).
3. **No source coverage regression.** The 14-source active registry must remain ingestable end-to-end after each PR.
4. **Import graph proof required** before touching `contract_sweeper/pipeline/`.
5. **Active-source registry must be enumerated** in any PR body that archives expansion downloaders.
6. **Required PR body sections** (every PR):
   - Import check summary (`rg` results showing zero live imports of moved paths).
   - CI/test command and result (`python3 -m pytest -q`).
   - Full list of moved files with old → new paths.
   - Explicit "no source coverage loss" statement.
   - Rollback instruction (single `git revert <sha>` or `git mv` reversal block).

---

## 2. Out of scope for this PR

- Moving, renaming, deleting, or merging any `.py` file.
- Rewriting any module body, even to inline a micro-helper.
- Creating `archive/r4_legacy/`.
- Re-running pytest beyond what is needed to confirm `main` is green.
- Updating `reports/current_status.json` (next PR's job).

---

## 3. Staged PR sequence (scope definitions only)

Each entry below is a **scope spec** for a future PR. Order is risk-ascending; later PRs may not start until earlier ones merge and Architect re-approves.

### PR-0 — Establish archive root (setup-only)
- **Action:** Create `archive/r4_legacy/.gitkeep` only. No source deletions in PR-0.
- **Explicitly excluded:** `scripts/highergov_manifest.py` is **not** removed in PR-0 (see §6 P1 Review Adjustment).
- **Approval gate:** Architect confirmation that the archive root layout is acceptable.
- **Evidence required:** Diff shows only the new directory marker; `rg "archive/r4_legacy" -n` returns no live import references.
- **Live source deletions:** Permitted in PR-0 only if a later evidence package proves 0 inbound runtime use. The HigherGov manifest does not meet this bar (see §6); any future deletion of a live module requires its own approval gate after a refactor PR removes its consumers.

### PR-1 — Archive dead `scripts/run_*.py` wrappers
- **Scope:** Move the subset of the 29 `scripts/run_*.py` wrappers whose target pipeline module is itself already archive-eligible (per `docs/MODULE_REDUCTION_PLAN.md`) **and** which appear in zero CI workflow file under `.github/workflows/`.
- **Pre-PR proof to gather:**
  1. For each candidate wrapper, identify the single pipeline module it imports.
  2. Cross-check that module against the `ARCHIVE` set in `module_inventory.csv`.
  3. `rg <wrapper_name>` across `.github/`, `Makefile`, `run_all.py`, and `docs/` — must return zero live invocations.
- **Result:** Candidate list goes into PR body; wrappers that fail any check stay on `main` for a later PR.
- **Approval gate:** Architect signs off on the candidate list before any `git mv`.

### PR-2 — Archive standalone analysis / dev-tooling scripts
- **Scope (from `docs/MODULE_REDUCTION_PLAN.md` ARCHIVE list):**
  - `scripts/dominance_analysis.py`
  - `scripts/analyze_prime_sub.py`
  - `scripts/triage_misc_drop.py`
  - `scripts/scan_for_secrets.py`
  - `scripts/regenerate_registry_json.py`
  - `scripts/parse_highergov_pdfs.py`
  - `data/raw/SAM/test_sam.py`
- **Removed from candidate list (P1 finding):** `scripts/fetch_highergov_api.py` — live, invoked from `run_all.py` when `HIGHERGOV_API_KEY` is set (see §6).
- **Constraint:** None of these may be referenced by `run_all.py` or any test in `tests/`. Confirm with `rg` before move.

### PR-3 — Archive `validation/cache_audit.py` + `pipeline/credential_unblock_plan.py`
- **Scope:** Two low-import modules from the ARCHIVE list.
- **Pre-PR proof:** Import graph snippet showing each module's inbound edges and the rationale that each consumer can switch to the canonical replacement (named explicitly in the PR body).
- **Note:** This PR begins to touch `contract_sweeper/pipeline/` and therefore triggers the **import graph proof** invariant (§1.4).

### PR-4 — Expansion downloader archive (gated)
- **Blocked until:** PR body includes the **complete 14-source active registry** (canonical names + entry points). The expansion downloaders being archived must be disjoint from that registry.
- **Scope:** Subset of the 62 expansion download scripts identified in the inventory baseline that are not referenced by the active 14 sources.

### PR-5 … PR-N — Merge groups (deferred, not in this scope plan)
The 12 merge groups in `docs/MODULE_REDUCTION_PLAN.md` (e.g., `source_mappers.py`, `run_pipeline.py`, `asset_linkers.py`) involve **logic rewrites** and therefore violate the archive-only invariant if combined with moves. They require a **separate Architect approval** authorizing logic consolidation, and are explicitly **out of scope** for the archive PR series defined above.

---

## 4. Approval gates summary

| Gate | Owner | Unblocks |
|------|-------|----------|
| G0 | Architect | This scope plan accepted → PR-0 may open |
| G1 | Architect | PR-0 merged + import proof for run-wrapper candidates → PR-1 may open |
| G2 | Architect | PR-1 merged → PR-2 may open |
| G3 | Architect | Import-graph proof for `contract_sweeper/pipeline/` accepted → PR-3 may open |
| G4 | Architect | 14-source active registry attested in PR body → PR-4 may open |
| G5 | Architect | New approval explicitly authorizing logic-merge PRs → PR-5+ may open |

---

## 5. Next command

```
# After Architect re-confirms this scope plan (post P1 patch), open PR-0:
git checkout -b claude/archive-root-setup
mkdir -p archive/r4_legacy && touch archive/r4_legacy/.gitkeep
# PR-0 is setup-only: no source deletions, no HigherGov changes.
```

No file movement performed by this PR.

---

## 6. P1 Review Adjustment (Codex review of PR #73)

Codex P1 review surfaced live runtime references that invalidate the
original PR-0 deletion target and one PR-2 archive candidate. Both
modules remain **live** and are removed from any archive/deletion scope
in this plan until a separate refactor PR detaches their consumers.

| Module | Status | Live consumer (P1 evidence) | Required precondition before any archive/delete PR |
|--------|--------|-----------------------------|----------------------------------------------------|
| `scripts/highergov_manifest.py` | **Keep — live** | `scripts/normalize_expansion_inputs.py` imports `HIGHERGOV_MANIFEST` | Refactor PR moves `HIGHERGOV_MANIFEST` to canonical `source_registry` and switches the consumer; only then may a deletion PR open |
| `scripts/fetch_highergov_api.py` | **Keep — live** | `run_all.py` imports/runs it when `HIGHERGOV_API_KEY` is set | Refactor PR consolidates HigherGov fetch into the active downloader path; only then may an archive PR open |

**Net effect on this scope plan:**
- PR-0 is reduced to archive-root setup (see §3 PR-0).
- PR-2 candidate list no longer includes `scripts/fetch_highergov_api.py`.
- A new **refactor PR series** (out of scope for this plan) is required before either HigherGov module can be archived or deleted.

---

## 7. Validation requirement for every future archive candidate

Each candidate module (regardless of PR number) must pass **all four**
checks below before being added to a PR body. Failure of any check
returns the module to KEEP and blocks the PR.

1. **`rg` / import check** — `rg -n "<module_stem>" --type py` returns zero hits outside the file itself and its tests.
2. **`run_all.py` reference check** — `rg -n "<module_stem>" run_all.py` returns zero hits; conditional/env-gated invocations (e.g. `if HIGHERGOV_API_KEY`) count as live references.
3. **`pytest`** — `python3 -m pytest tests/ -q` passes before and after the move with no new failures or skips.
4. **Source-coverage regression check** — The 14-source active registry remains fully ingestable end-to-end; PR body explicitly enumerates which of the 14 sources, if any, the candidate touches and confirms each remains reachable through the canonical entry point.

The PR body must include the raw output (or trimmed evidence block) for
all four checks per candidate.
