# moneysweep-pr — Gap Analysis & Code Optimization Review

_Generated 2026-09-12 against `claude/gap-analysis-code-optimization-72zkfr`, branched from
`main` at `b16cf31`._

Unlike `RECOMMENDATIONS.md` and the retired `docs/CODE_GAP_AND_WORKFLOW_AUDIT.md`, this
review is **not advisory-only**. The findings marked **FIXED** were corrected in the same
pull request that introduced this document; everything else is recorded for the maintainer
to sequence deliberately, consistent with the `no_broad_audits_without_approval` and
`delta_only_reporting` controls in `reports/current_status.json`.

Every finding below was **measured**, not inherited from an earlier audit. Where a measurement
contradicted an existing document, the contradiction is called out.

## Method & provenance

| Aspect | Value |
|--------|-------|
| Toolchain | `ruff==0.16.5`, `mypy==2.3.1` — the versions pinned in `requirements-dev.txt`, not sandbox defaults |
| Python | 3.11.15 (the `.python-version` / `pyproject.toml` baseline) |
| Suite baseline | 2,945 passed · 1 failed · 9 skipped · **54.57%** coverage, 135s |
| Measured | working tree, git object store, and the GitHub Actions API |

> **A version caveat that changed a finding.** An initial pass using the sandbox's
> `mypy 1.19.1` reported two type errors in `moneysweep/capital_control/`. Under the pinned
> `mypy 2.3.1` both **disappear** — the newer release narrows `x in (None, 0)` correctly.
> They were dropped rather than "fixed". Re-verify lint and type findings against the pinned
> toolchain before acting on them.

---

## A. Gating quality bar — three gates were red on `main`

All three trace to `fca3264` ("Preserve HUD DRGR pursuit and validator drift repair"), one of
three consecutive **direct-to-`main` pushes** (`fca3264`, `936fba9`, `f17bc8a`) that carry no
`(#NNN)` merge suffix, unlike the 26 commits before them. They bypassed both the pull-request
path and the `AGENTS.md` required change protocol.

| # | Finding | Evidence | Status |
|---|---------|----------|--------|
| A1 | `ruff check .` failed | `F401` unused `pathlib.Path`, `tests/test_audit_hud_drgr_authorized_sources.py:1` | **FIXED** |
| A2 | `ruff format --check .` failed | 2 files unformatted | **FIXED** |
| A3 | GUI-capability parity failed | `.federation/check_gui_parity_with_extensions.py` exits 1 on pristine `origin/main` with 9 unpaired candidates for `scripts/audit_hud_drgr_authorized_sources.py`, which landed with no classification | **FIXED** |

A3 was fixed through the documented `exceptions` mechanism in
`.federation/gui-capabilities.json`, mirroring the existing
`compare-entity-products-terminal-analysis` precedent. **`gui-parity-baseline.json` was
deliberately left untouched** — `AGENTS.md` forbids regenerating it to clear a gate.

### A4 — The skillpack conformance gate is self-invalidating by construction — **NOT FIXED**

`tests/test_unified_skillpack_conformance.py::test_full_conformance` is the suite's single
failure, and it is structural rather than incidental:

```
tools/validate_unified_skillpacks.py:129
    git diff --name-only {pinned_base_commit}..HEAD
→ any path outside manifest["allowed_change_paths"] is an error
```

`allowed_change_paths` is four entries (`.claude/skillpacks/`, the conformance workflow, the
validator, its test). `pinned_base_commit` lives in `.claude/skillpacks/{BINDING,MANIFEST}.json`
and currently reads `fca3264`. The failure today is:

```
out-of-scope change: docs/BACKEND_ASSESSMENT_AND_DEVELOPMENT_PLAN.md
```

— a documentation file added by PR #578 *after* the pin was set.

**Every commit that touches anything outside those four paths fails this gate until someone
re-pins; re-pinning is itself a commit that moves `main`, which re-invalidates the pin on the
next change.** Commits `936fba9` ("Refresh skillpack conformance baseline") and `f17bc8a`
("Rebind skillpack conformance baseline") are two consecutive direct pushes doing exactly
this. This PR also trips it, and deliberately does not re-pin: chasing the pin would paper
over the defect.

_Recommendation:_ the gate should compare the **merge-base** against `HEAD`, or scope the
diff to the skillpack surface it actually governs, rather than pinning to a moving branch tip.

---

## B. The gates measured less than they appeared to

| # | Finding | Status |
|---|---------|--------|
| B1 | ~3,000 LOC outside the type gate — `pyproject.toml` checked only `moneysweep/` + `scripts/`, excluding `server/` (the entire FastAPI backend), `shared/`, `readiness/`, `desktop/` | **FIXED** |
| B2 | The same packages sat outside the coverage denominator, despite 7 test files importing `server.backend.*` — the API surface was tested but not counted | **FIXED** |
| B3 | `server/` and `server/backend/` carry no `__init__.py` yet `server/backend/case_manager_app.py:9` does `from . import case_manager_api` | **FIXED** (config, not new files) |
| B4 | The `run_all.py` decomposition was never finished | **NOT FIXED** |

### B3 — why this was fixed with config rather than `__init__.py`

The obvious fix is the wrong one. `server/backend/` is an implicit namespace package, so mypy
refused it outright (`No parent module -- cannot perform relative import`) — the mechanical
reason the backend was never type-checked. But adding `server/backend/__init__.py` would
reopen A3: `scripts/check_gui_parity.py:209` collects backend files through `_iter_files()`,
which `rglob`s every `.py` under `discovery.backend_roots` (line 183), so a new `__init__.py`
becomes a new unpaired `python_module` candidate in the parity inventory.

Setting `namespace_packages = true` + `explicit_package_bases = true` resolves the import for
mypy and adds no files at all.

### B1/B2 — what the blind spot was hiding

Widening the type gate surfaced **8 real errors**, all loose-typing artifacts rather than live
bugs, each fixed without behavior change:

| Site | Error |
|------|-------|
| `readiness/moneysweep_finance_lane.py:232,235` | `union-attr` ×4 on a heterogeneous report dict |
| `server/backend/campaign_finance.py:94` | `float(object)` |
| `server/backend/ownership_api.py:73,74` | indexing an `object` |
| `server/backend/case_manager_app.py:31` | `Optional` repository attribute |

mypy now checks **558** source files, up from 538, clean.

Widening the coverage denominator **raised** the total rather than diluting it:

| | Statements | Coverage |
|---|---|---|
| Before | 57,949 | 54.57% |
| After | 59,102 | **54.75%** |

because the newly-counted code is **64%** covered — above the repo average. The
`--cov-fail-under=44` floor is therefore unchanged and `pytest.ini`'s "raise, never lower"
rule was never engaged. The genuinely thin spots the blind spot concealed:

| Module | Coverage | Note |
|--------|----------|------|
| `desktop/secrets.py` | **0%** | credential handling |
| `desktop/launch.py` | 0% | |
| `desktop/app_server.py` | 0% | |
| `server/backend/government_changes.py` | 31% | |
| `server/backend/main.py` | 35% | the primary read API |
| `server/backend/ownership_api.py` | 35% | |

### B4 — `run_all.py` decomposition is incomplete

`RECOMMENDATIONS.md` #5 records the monolith decomposition as landed (#202). In fact
`run_all.py` is an 83-line profile dispatcher that delegates at line 74 to an untouched
**2,073-line** `run_all_legacy.py`, which remains outside the type gate, outside the coverage
denominator, and carries a blanket `E402` ignore (`pyproject.toml:59`). The dispatcher was
added; the decomposition was not done.

---

## C. Robustness and optimization

### C1 — Module-level `sys.exit()` on `ImportError` — **FIXED**

Four modules aborted the **interpreter** at import time when an optional dependency was
missing, instead of raising a catchable exception:

`scripts/merge_legislapr_registry.py`, `scripts/regenerate_registry_json.py`,
`scripts/validate_skills.py`, `scripts/network_graph.py`

Measured effect, before the fix — with PyYAML absent:

```
INTERNALERROR> SystemExit: 2
mainloop: caught unexpected SystemExit!
630 tests collected, 100 errors
```

One missing dependency took down the entire pytest run. After the fix, the same condition
yields a clean, attributable per-file collection error with the install hint preserved. This
never fires in CI because dependencies are installed there — which is precisely why it
survived.

> Two further `except ImportError` sites (`scripts/download_cdbg_dr.py:450`,
> `scripts/sam_enrichment.py:158`) were examined and are **not** defects: both are
> function-local and degrade gracefully.

### C2 — `BaseDownloader` class has zero production users — **NOT FIXED**

`moneysweep/runtime/base_downloader.py` (421 LOC) provides both a functional core and an OO
wrapper. Measured adoption across the 95 `scripts/download_*.py`:

| | Count |
|---|---|
| Import the **functional helpers** (`build_session`, `http_get_json`, …) | 32 of 95 |
| Do not import the module at all | 63 of 95 |
| Still call `requests.get/post/Session` directly | 69 of 95 |
| Use the **`BaseDownloader` class** | **0** |

The class's only references anywhere outside its own module are in
`tests/test_base_downloader.py`. In fairness to the design, the module docstring states the
class "is for new downloaders" while the functional core exists so existing ones can migrate
incrementally — so this is an unused abstraction by design, not a bug. But the migration is
**34% complete** and has stalled, and `RECOMMENDATIONS.md` #4 records this work as landed
(#201/#204) when two thirds of the duplication it targeted is still in place.

_Recommendation:_ either finish the migration for the 63 non-adopters or retire the unused
class; carrying both a stalled migration and an unexercised abstraction is the worst of both.

### C3 — Deferred ruff rule families: a sized backlog — **NOT FIXED (by design)**

`pyproject.toml` documents `select = ["E4","E7","E9","F"]` with broader families deliberately
deferred. Measuring that backlog:

| Rule | Count | Rule | Count |
|------|-------|------|-------|
| `TRY003` | 622 | `PERF401` | 143 |
| `I001` (unsorted imports) | 262 | `RUF100` (unused `noqa`) | 100 |
| `TRY400` | 202 | `UP035` | 76 |
| `UP017` | 169 | `B905` (`zip` without `strict`) | 39 |
| `ARG001` | 157 | | |

~2,600 findings total. `I001` (262, autofixable) and `RUF100` (100 — unused suppressions that
are pure noise) are the cheapest wins if the ratchet is ever advanced.

### C4 — Committed build exhaust the repo already decided to ignore — **NOT FIXED (maintainer's call)**

`reports/local_analysis/` holds **152 tracked files / 5.2 MB** — 61 `.log`, 49 `.txt`, 37
`.exitcode`, 3 coverage `.xml` — from local debugging sessions dated 2026-07-05/06, referenced
by **zero** code, tests, or workflows. That is ~73% of the 7.1 MB `reports/` tree.

The decisive detail: **`.gitignore:164` already ignores `reports/local_analysis/`**, describing
it as "agent scratch, not part of the committed audit trail". Ignore rules do not apply to
already-tracked paths, so the 152 files the rule was written to exclude are still in the index:

```
$ git check-ignore -v --no-index reports/local_analysis/.../00_coverage_baseline.xml
.gitignore:164:reports/local_analysis/    reports/local_analysis/.../00_coverage_baseline.xml
$ git ls-files reports/local_analysis | wc -l
152
```

So `git rm --cached -r reports/local_analysis/` would *implement* the repo's own stated policy
rather than override the preserve-for-auditability posture — the posture was already decided
against this content. Still left to the maintainer because it removes 5.2 MB from the index and
is a content decision, not a quality-gate one.

> **A correction to this review's own starting hypothesis.** An initial scan flagged "41
> byte-identical tracked blob groups, 2.7 MB wasted". On inspection most are **legitimate**:
> macOS `.app` bundle resources and `dashboard/public/` build inputs duplicated from
> `assets/branding/` are structural requirements, not waste. Only the round-suffixed
> `data/exports/*_r4_9h.csv` ↔ `data/review_queue/*` pairs are genuine redundancy. The
> headline number was wrong and is withdrawn.

### C5 — `artifacts/` was not gitignored — **FIXED**

`.federation/check_gui_parity_with_extensions.py:22` writes
`artifacts/gui-capabilities-merged.json` on every run. The path was absent from `.gitignore`,
so it surfaced as an untracked file after any local parity check and was one `git add -A` away
from being committed — a 100 KB derived manifest that is never a source of truth. Added to
`.gitignore` alongside the existing `reports/local_analysis/` rule.

---

## D. Governance drift — **NOT FIXED**

| # | Finding | Evidence |
|---|---------|----------|
| D1 | The skillpack pin is stale again | See A4 |
| D2 | `reports/current_status.json` — the declared machine-readable source of truth — is stale | `main_sha: 3155201…` (PR #486) vs. actual `main`; `generated_at: 2026-08-20`; self-declares `evidence_snapshot_state: "STALE_NOT_RECERTIFIED"` |
| D3 | `STATUS.md` test baseline is stale | Dated 2026-07-26; its own text warns the preceding row was ~10 weeks and ~1,900 tests out of date. Current measured baseline: **2,945 passed · 9 skipped · 54.75%** |
| D4 | Case-manager write API has no authentication | `server/backend/case_manager_api.py:155,192,207,224,…` — `X-Case-Clearance` and `X-Case-Actor` are plain `Header(default=None)` parameters. No `Depends`, `Security`, `HTTPBearer`, or middleware anywhere in the router. Any caller can self-assert `restricted` clearance or any actor identity. **Confirms in code** the claim in `docs/BACKEND_ASSESSMENT_AND_DEVELOPMENT_PLAN.md`; it remains the most concrete active security gap and is sequenced first in that document's plan |

---

## Priority matrix for what remains

| # | Area | Recommendation | Effort | Risk | Priority |
|---|------|----------------|--------|------|----------|
| D4 | Security | Real identity for case-manager clearance/actor; interim shared-secret gate on write endpoints | M | Med | **P0** |
| A4 | CI correctness | Make the skillpack gate diff against merge-base, not a pinned branch tip | S | Low | **P0** |
| B2 | Test coverage | Cover `desktop/secrets.py` (0%, credential handling) and `server/backend/main.py` (35%) | M | Low | P1 |
| C2 | Duplication | Finish or retire the `BaseDownloader` migration (63 non-adopters) | L | Med | P1 |
| B4 | Architecture | Decompose `run_all_legacy.py` (2,073 LOC); bring into type + coverage scope | L | Med | P1 |
| D2/D3 | Governance | Re-certify `reports/current_status.json` and `STATUS.md` from an emitted measurement | S | Low | P2 |
| C3 | Lint | Advance the ratchet: `I001` (262) and `RUF100` (100) first | S | Low | P2 |
| C4 | Hygiene | `git rm --cached -r reports/local_analysis/` (5.2 MB) — completes the intent `.gitignore:164` already declares | S | Low | P2 |

## Verification of the changes in this PR

```
ruff check .                                        All checks passed
ruff format --check .                               1100 files already formatted
python -m mypy                                      Success: 558 source files
python .federation/check_gui_parity_with_extensions.py   PASS (baseline untouched)
python -m pytest -q                                 2945 passed · 9 skipped · 54.75%
python -m pytest --collect-only -q                  2954 collected, no INTERNALERROR
```

The one remaining failure, `test_unified_skillpack_conformance`, is finding A4 — pre-existing,
structural, and reproduced on pristine `origin/main`.
