# moneysweep-pr — Gap Analysis & Code Optimization Review

_Findings measured 2026-09-12 against `main` at `b16cf31`; revised 2026-09-15 after merging
`main` at `7b467ff`, which resolved findings A1-A4 independently. Section A records that._

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
| Suite at `b16cf31` (as found) | 2,945 passed · 1 failed · 9 skipped · **54.57%** coverage |
| Suite after this PR, merged with `7b467ff` | **2,947 passed · 0 failed · 9 skipped · 54.65%** |
| Measured | working tree, git object store, and the GitHub Actions API |

> **A version caveat that changed a finding.** An initial pass using the sandbox's
> `mypy 1.19.1` reported two type errors in `moneysweep/capital_control/`. Under the pinned
> `mypy 2.3.1` both **disappear** — the newer release narrows `x in (None, 0)` correctly.
> They were dropped rather than "fixed". Re-verify lint and type findings against the pinned
> toolchain before acting on them.

---

## A. Gating quality bar — three gates were red, and `main` fixed them first

This section is the one the review got overtaken on, and it is recorded that way rather than
rewritten to look prescient.

When this branch was cut from `b16cf31` (2026-09-12), three gating checks were red on `main`,
all traceable to `fca3264` — one of three consecutive **direct-to-`main` pushes**
(`fca3264`, `936fba9`, `f17bc8a`) carrying no `(#NNN)` merge suffix, unlike the 26 commits
before them. They bypassed both the pull-request path and the `AGENTS.md` change protocol:

| # | Finding as measured at `b16cf31` | Resolution |
|---|---|---|
| A1 | `ruff check .` failed — `F401` unused `pathlib.Path`, `tests/test_audit_hud_drgr_authorized_sources.py:1` | Fixed on `main` |
| A2 | `ruff format --check .` failed — 2 files unformatted | Fixed on `main` |
| A3 | GUI-capability parity exited 1 with 9 unpaired candidates for `scripts/audit_hud_drgr_authorized_sources.py`, which landed unclassified | Fixed on `main`, **better than this PR's attempt** |
| A4 | The skillpack conformance gate failed on every PR by construction | Fixed on `main` |

**All four were resolved independently on `main` between 2026-09-12 and 2026-09-15**, while
this branch was blocked behind the Actions outage. This PR originally fixed A1–A3 and
recommended a fix for A4; those changes have been withdrawn from it in favour of main's,
and the analysis is kept because the *pattern* it documents is still live (see below).

### A3 — main's fix is the better one, and this PR deferred to it

This branch classified the script through the `exceptions[]` mechanism in
`.federation/gui-capabilities.json`, mirroring the `compare-entity-products-terminal-analysis`
precedent. `main` instead added a capability classification —
`.federation/gui-capabilities.extensions/hud-drgr-authorized-pursuit.json`,
`classification: "internal"`, covering the identical 9 candidate IDs and binding
`tests/test_audit_hud_drgr_authorized_sources.py` as its backend test, with
`tests/test_hud_drgr_gui_classification.py` asserting the shape.

That is the right call and this PR's waiver was removed rather than merged alongside it.
An `exceptions[]` entry is a **time-limited waiver** — this one carried
`expires_on: 2026-12-01` — so it would have re-opened the gate in December for something
that is permanently and correctly classified as internal infrastructure. `AGENTS.md`
explicitly permits the classification route: "Pure infrastructure may be classified
`internal` with a concrete rationale."

### A4 — the gate was self-invalidating by construction, and is no longer enforced

`tools/validate_unified_skillpacks.py` ran:

```
git diff --name-only {pinned_base_commit}..HEAD
→ any path outside manifest["allowed_change_paths"] is an error
```

`allowed_change_paths` is four entries. `pinned_base_commit` tracked `main`'s tip, so **every
commit touching anything else failed the gate until someone re-pinned — and re-pinning is
itself a commit that moves `main`, re-invalidating the pin.** Commits `936fba9` ("Refresh
skillpack conformance baseline") and `f17bc8a` ("Rebind skillpack conformance baseline") are
two consecutive direct pushes doing exactly that.

`main` has since removed the enforcement, and its own code comment reaches the same
diagnosis independently — "a repo-wide change-freeze that blocked ordinary, unrelated PRs
(see `governance/change_log.json`)". The check is now informational. `test_full_conformance`
passes.

### A5 — capabilities are landing unclassified — **instance closed; prevention still open**

> **Amended 2026-09-19.** As first written this finding was wrong on its stated cause, and has
> since gone stale on its facts. Both corrections are below rather than quietly edited out.

**As measured at `7b467ff`.** `scripts/download_hacienda_sut_ivu.py` landed via `a38025a`
("Graduate hacienda_sut_ivu to a live PDF producer", #582) **without the classification
`AGENTS.md` step 1 requires**, so the parity gate was red on `main`:

```
FAIL gui-parity ... new=5 manifest_issues=0
ANALYSIS_NOT_GUI_RENDERED: analysis_module:scripts/download_hacienda_sut_ivu.py
ANALYSIS_NOT_GUI_RENDERED: ...:discover_pdf_urls | :parse_pdf | :run
TERMINAL_REQUIRED:         cli_surface:scripts/download_hacienda_sut_ivu.py
```

That was accurate when written, and verified on a clean worktree of `origin/main`.

#### Correction 1 — the cause was mis-attributed

This finding was originally titled "the direct-push pattern is still live" and presented #582
as another instance of the direct-to-`main` pushes behind A1–A4. **It is not.** `a38025a`
carries a `(#582)` suffix and a single parent: it came through the pull-request path. The
A1–A4 commits did not:

| Commit | Route |
|---|---|
| `a38025a` — hacienda SUT/IVU producer (#582) | **pull request** |
| `fca3264` — HUD DRGR pursuit + validator drift | direct push, no PR |
| `936fba9` — refresh skillpack baseline | direct push, no PR |
| `f17bc8a` — rebind skillpack baseline | direct push, no PR |

The recurring gap is not *how* the commit arrived but that **a capability can land
unclassified either way**. Review did not catch it on the PR route.

#### Correction 2 — the instance is closed and the gate is green

`b306731` ("Classify the hacienda SUT/IVU producer for GUI parity", #587) landed shortly after
this finding was written, adding
`.federation/gui-capabilities.extensions/hacienda-sut-ivu-producer.json`
(`classification: "internal"`, `requires_terminal: false`, covering exactly the 5 candidate IDs
listed above) plus `tests/test_hacienda_sut_ivu_gui_classification.py` — the same mechanism
`main` used for the HUD DRGR script in A3. On `main` at `255eff2`:

```
PASS gui-parity  current=2945 mapped=746 legacy=2195 new=0 manifest_issues=0
```

_Recommendation (unchanged, and better supported by Correction 1):_ make the GUI-parity gate a
**required status check** on `main`. Two structurally different routes — an unreviewed direct
push and a reviewed pull request — each let an unclassified capability through, and each was
repaired only after the fact. Human review is demonstrably not the control that catches this;
an enforced gate is. The remediation loop itself is working (both instances closed within
hours, through the correct classification mechanism rather than a baseline regeneration), so
what remains is prevention, not active breakage.

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

## D. Governance drift — D4 **FIXED**; D1–D3 open

| # | Finding | Evidence |
|---|---------|----------|
| D1 | ~~The skillpack pin is stale again~~ — **resolved on `main`**, enforcement removed | See A4 |
| D2 | `reports/current_status.json` — the declared machine-readable source of truth — is stale | `main_sha: 3155201…` (PR #486) vs. actual `main`; `generated_at: 2026-08-20`; self-declares `evidence_snapshot_state: "STALE_NOT_RECERTIFIED"` |
| D3 | `STATUS.md` test baseline is stale | Dated 2026-07-26; its own text warns the preceding row was ~10 weeks and ~1,900 tests out of date. Current measured baseline: **2,947 passed · 9 skipped · 54.65%** |
| D4 | ~~Case-manager write API has no authentication~~ — **FIXED** (interim) | `server/backend/case_manager_api.py` derived identity from headers: `_actor()` returned `value or "anonymous"`, `_clearance()` returned `value or "public"`, so absent headers still authorized. Two concrete defects: `X-Case-Clearance: restricted` set the caller's rank in `VISIBILITY_RANK` directly (**privilege escalation**), and `X-Case-Actor` was recorded as the actor on all 11 write commands (**audit-trail forgery**). Both are now derived from a verified credential via `server/backend/case_manager_auth.py` and are unreadable from the request; unconfigured deployments **fail closed** with 503 rather than reverting to the old behavior. See A6 for what remains. |


### D4 follow-up — what the interim boundary does not cover

The fix binds identity to a credential; it is not the federation-wide identity provider
`docs/CASE_MANAGER_PHASE_1_API_CONTRACT.md` anticipates. Still outstanding:

- **Tokens are long-lived and hand-issued.** No rotation, expiry, or revocation beyond editing
  the identity file. Acceptable for a loopback-only service; not for a networked one.
- **Loopback is the transport boundary.** The service is still only safe to run bound to
  localhost. It is now *enforced* (403 off-box) rather than assumed, but that is a floor, not
  a substitute for transport auth.
- **The router remains unmounted on the main app**, served only by the standalone
  `case_manager_app`. Mounting it anywhere reachable would need the provider first.
- **No per-route authorization.** Any recognized identity may call any write route; clearance
  governs reads only. Command-level authorization is provider work.

---

## Priority matrix for what remains

| # | Area | Recommendation | Effort | Risk | Priority |
|---|------|----------------|--------|------|----------|
| D4 | Security | ~~Real identity for case-manager clearance/actor~~ — interim boundary landed; replace with the federation-wide identity provider when `thehub-pr` ships it | M | Low | P2 |
| A5 | Process | Make GUI-capability parity a required status check so an unclassified capability cannot land — it has slipped through on both the direct-push and the reviewed-PR route | S | Low | P1 |
| B2 | Test coverage | Cover `desktop/secrets.py` (0%, credential handling) and `server/backend/main.py` (35%) | M | Low | P1 |
| C2 | Duplication | Finish or retire the `BaseDownloader` migration (63 non-adopters) | L | Med | P1 |
| B4 | Architecture | Decompose `run_all_legacy.py` (2,073 LOC); bring into type + coverage scope | L | Med | P1 |
| D2/D3 | Governance | Re-certify `reports/current_status.json` and `STATUS.md` from an emitted measurement | S | Low | P2 |
| C3 | Lint | Advance the ratchet: `I001` (262) and `RUF100` (100) first | S | Low | P2 |
| C4 | Hygiene | `git rm --cached -r reports/local_analysis/` (5.2 MB) — completes the intent `.gitignore:164` already declares | S | Low | P2 |

## Verification of the changes in this PR

Measured on the merge of this branch with `main` at `7b467ff`, using the pinned toolchain
from `requirements-dev.txt` (`ruff==0.16.5`, `mypy==2.3.1`), not sandbox defaults:

```
ruff check .                                             All checks passed
ruff format --check .                                    1103 files already formatted
python -m mypy                                           Success: 559 source files
python -m compileall moneysweep scripts tests            OK
python -m pytest -q                                      2947 passed · 9 skipped · 54.65%
python .federation/check_gui_parity_with_extensions.py   FAIL  new=5 manifest_issues=0
```

The suite is **fully green** — the one failure present when this review began
(`test_unified_skillpack_conformance`) is gone, because `main` removed that gate's
enforcement (A4).

The parity gate is red, and **not on account of this PR**: all 5 unpaired candidates belong
to `scripts/download_hacienda_sut_ivu.py`, which arrived from `main` via #582. The identical
failure reproduces on a clean worktree of `origin/main` at `7b467ff` — same count, same five
candidate IDs. That is finding A5, left deliberately unfixed here.
