# Contract-Sweeper — Build Execution Sequence (75 tasks)

_Generated 2026-06-08. Companion to `docs/CODE_GAP_AND_WORKFLOW_AUDIT.md`._

**Ordering principle: execution efficiency, not ROI.** Tasks are queued so the build
moves forward **flawlessly** — each task's prerequisites are already done by the time you
reach it, so nothing has to be re-done, and no gate is switched on before the code can pass
it. Work top-to-bottom. The sequence is organized into **waves**; everything in a wave
depends only on earlier waves. Within a wave, order is the natural execution order.

Legend: **[done]** landed in PR that introduced this file · **(gate)** flips a CI/hook from
non-gating→gating · **(big-diff)** mechanical but touches many files — keep it in its own PR.

---

## WAVE A — Quality-gate tooling foundation
_Nothing can be cleaned or gated until the tools exist and are reproducible. Pure additions;
breaks nothing._

1. **[done]** Add `[tool.ruff]` config to `pyproject.toml` (rule set, line-length, exclude `archive/`). Prerequisite for every lint task.
2. **[done]** Add non-gating ruff lint CI job (`.github/workflows/lint.yml`, `continue-on-error: true`) — visibility without blocking, mirroring `mypy.yml`.
3. **[done]** Add ruff pre-commit hook (changed-files only) so new code stays clean from now on.
4. Add `requirements-dev.txt` (ruff, mypy, pytest, pytest-cov, types-PyYAML, types-requests) — single source for dev/CI tooling versions. Prerequisite for 5, 24, 56.
5. Pin the ruff version identically in `requirements-dev.txt` and the pre-commit `rev` — reproducible lint across local/CI.
6. Have the lint CI job install from `requirements-dev.txt` (not a floating `pip install ruff`) — depends on 4.

## WAVE B — Mechanical lint cleanup (enabled by A; must precede any lint gate)
_Bring the tree to zero lint errors before flipping the gate, so the gate goes green on day one._

7. **[done]** Apply `ruff check --fix` safe autofixes (248: F401 unused-import, F541 f-string). Mechanical. **(big-diff)**
8. **[done]** Resolve remaining **F841** unused-variable via `--unsafe-fixes` (binding dropped, side-effecting calls kept) + manual cleanup of no-op leftovers. One half-wired case (`external_blocker_freeze.py` physical evidence) retained with `# noqa: F841` + a follow-up note rather than silently deleted.
9. **[done]** Resolve **E402** module-import-not-at-top — `[tool.ruff.lint.per-file-ignores]` for the 6 files with intentional `sys.path` bootstraps / deliberately interleaved test imports.
10. **[done]** Resolve **E701/E702** multiple-statements-on-one-line — split (analyze_entity_profiles, analyze_power_network, generate_report, test_validation_gates).
11. **[done]** Resolve **E712/E731/E741** — `== True` → truthiness, lambdas → defs, `l` → `layer`.
12. **[done]** `ruff check .` → **All checks passed!**; full suite 1616 passed (1 pre-existing env-only failure unrelated to lint).
13. **[done] (gate)** Flipped the ruff lint CI job to blocking (removed `continue-on-error` in `lint.yml`).

## WAVE C — Formatting (isolated; do after lint so the two don't interleave)
_`ruff format` rewrites 507 files. Keep it surgical and reviewable._

14. **[done]** Strategy: one big-bang `ruff format .` in a dedicated PR (maintainer-approved), merged with a **merge commit** (not squash) so the format SHA persists for blame-ignore.
15. **[done]** Applied `ruff format .` (428 files, formatting only) — full suite still 1616 passed. **(big-diff)**
16. **[done]** Added the format commit SHA to `.git-blame-ignore-revs`.
17. **[done] (gate)** Added `ruff-format` pre-commit hook + gating `ruff format --check .` CI step.

## WAVE D — Type-safety hardening (after lint/format; mypy widening)
_Each step keeps the existing narrow mypy gate green while widening it._

18. **[done]** Fix the known `geo_attribution.py:172` dict-item return-type bug — annotation was `dict[str, dict[str, str]]` but the function returns `{by_fips, by_alias}` indexes (one more level of nesting).
19. **[done]** Remove the `geo_attribution.py` exclude from the mypy pre-commit hook — `mypy contract_sweeper/runtime/` now clean across all 19 files.
20–22. **[done]** Type-clean `contract_sweeper/` (pipeline/ + query/ are already inside the `files=["contract_sweeper"]` scope). Fixed ~15 errors: implicit-`Optional` defaults, `str | None` coercion in the canonical_v1 bridge, a `Query | EntityQuery` union for `FileCache.put`/`QueryResult` (via `TYPE_CHECKING`), default-arg-lambda inference, and a few annotations. All behavior-preserving (suite still 1616 passed).
23. **[done]** Added `types-requests` to `requirements-dev.txt` — required because mypy's `import-untyped` (stubs available on PyPI) is **not** suppressed by `ignore_missing_imports`. Dropping `ignore_missing_imports` per-module is still future work.
24. _Pending_ — bring `scripts/` into mypy scope. Currently deferred via `follow_imports = "silent"`, so script errors are followed-for-symbols but not reported.
25. **[done] (gate)** Flipped `.github/workflows/mypy.yml` to gating (removed `continue-on-error`); `python -m mypy` → clean across 92 files under the pinned mypy 1.11.2.

## WAVE E — Cross-repo contract hardening (corrects the #216 false positive)
_See `docs/CODE_GAP_AND_WORKFLOW_AUDIT.md` §B1 correction._

26. Add a one-line provenance comment at **each** `EXPORT_CONTRACT_VERSION` (federation package vs. finance lane) so the two contracts are never conflated again.
27. Author `schemas/contract_sweeper_finance_lane_report.schema.json` for the finance-lane report — the real B1 gap.
28. Add a test validating an emitted finance-lane report against schema 27 and asserting `export_contract_version == "1.0.0"` — depends on 27.
29. Add a conformance-fixture freshness check for `exports/conformance/v1_2/` so the federation package can't silently drift from its schema.
30. Centralize each contract version into a single importable constant (one per contract) — removes the duplicate literal in `scripts/build_export_package.py` vs. samples.

## WAVE F — Coverage instrumentation (before adding the floor, measure)
_Set the ratchet only after you know the number it should start at._

31. **[done]** `pytest.ini` already emits `--cov-report=term-missing` (total %) and `coverage.xml`; measured baseline ≈ 44.5%.
32. **[done]** **(gate)** Added `--cov-fail-under=42` to `pytest.ini` — locks the coverage baseline (~2.5 pts below current; ratchet upward in Wave G).

## WAVE G — Tests for untested critical paths (#215; ratchet coverage as you go)
_Highest-blast-radius modules first. Each new test file lets you raise the floor._

33. Unit-test `contract_sweeper/pipeline/credentialed_endpoint_execution.py` (mock HTTP + credentials).
34. Unit-test `contract_sweeper/pipeline/manual_import_dropzone.py` (operator-supplied file ingestion).
35. Unit-test `contract_sweeper/pipeline/source_materialization.py`.
36. Unit-test `contract_sweeper/pipeline/scoped_unfreeze_materialization.py`.
37. **[done]** Unit-test `contract_sweeper/runtime/retry_runtime.py` — `tests/test_runtime_helpers.py` (success/transient-recovery/exhaustion + exception narrowing + backoff/jitter).
38. **[done]** Unit-test `contract_sweeper/runtime/pagination_runtime.py` — `tests/test_runtime_helpers.py` (multi-page walk, start_marker, max_pages guard).
39. **[done]** Unit-test `contract_sweeper/runtime/file_hash_runtime.py` — `tests/test_runtime_helpers.py` (hashlib parity, empty + multi-chunk).
40. **[done]** Unit-test `contract_sweeper/runtime/evidence_tiers.py` — `tests/test_runtime_helpers.py` (tier derivation/caps, confidence, OCR scoring, claim-tier mapping).
41. **[done]** Unit-test `contract_sweeper/runtime/risk_signal_gates.py` — already covered by `tests/test_risk_signals.py` (all five gates + `run_all_gates`).
42. Adapter error/credential-path tests: `query/adapters/sam.py`.
43. Adapter error/credential-path tests: `query/adapters/highergov.py`.
44. Adapter error/credential-path tests: `query/adapters/ckan_metastore.py`.
45. Adapter error/credential-path tests: `query/adapters/cms_socrata.py`.
46. Adapter error/credential-path tests: `query/adapters/ofac.py`.
47. Narrow the broad `except Exception: return []` in `runtime/validation_gates.py` (#221) + add a malformed-file regression test — safe now that the path is covered.
48. **(gate)** Raise `--cov-fail-under` to the new, higher post-33–47 baseline — ratchet up.

## WAVE H — Dependency & supply-chain automation (after dev-deps exist)
49. **[done]** Add `.github/dependabot.yml` (`pip` + `github-actions`, weekly, `repo-governance` label) — #219.
50. **[done]** Add `.github/workflows/lockfile.yml` — gating check that re-compiles `requirements.lock` from `requirements.in` with uv and fails on drift.
51. **[done]** `uv` already produces `requirements.lock` deterministically from `requirements.in`; the lockfile-drift check (50) enforces it. No `pip-tools` migration needed.
52. **[done]** Add `.github/workflows/pip-audit.yml` — scheduled (+ dispatch) `pip-audit` against `requirements.lock`, report-only to start.

## WAVE I — Governance & community scaffolding (independent; low coupling)
53. **[done]** Add `LICENSE` — **MIT** (with a note that ingested public data keeps its originating terms) — #218.
54. **[done]** Add `CONTRIBUTING.md` documenting the fresh-`main` branch/PR flow **and** the now-gating quality gates (ruff lint/format, mypy, pytest, lockfile).
55. **[done]** Add `.github/CODEOWNERS` reflecting the Architect-gate ownership (maintainer `@jotaele44`; federation contract + CI flagged explicitly).
56. **[done]** Add `.github/pull_request_template.md` mirroring the existing review checklist (gates + scope/risk + federation-contract flag).
57. **[done]** Add `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1, adopted by reference).
58. **[done]** Add `SECURITY.md` (private disclosure policy) — pairs with dependabot/pip-audit.

## WAVE J — Release & versioning (after contracts are schematized + governance exists)
59. Add a root `CHANGELOG.md` (Keep-a-Changelog) — #220.
60. Add a release-tagging workflow keyed to `export_contract_version` bumps — depends on 26/30/59.
61. Document the cross-repo release/handshake procedure with `spiderweb-pr` in `docs/federation_readiness.md`.

## WAVE K — Developer experience (wraps the now-stable command set)
62. Add a `Makefile` (or `justfile`) with `lint` / `format` / `type` / `test` targets wrapping Waves A–G commands.
63. Add an `.editorconfig` consistent with the ruff line-length.
64. **(gate)** Add a `pre-commit run --all-files` CI job — green only because Waves B–D made it so.
65. Add a "Development" section to `README.md` pointing at the Makefile + gates.

## WAVE L — Repo hygiene / history (most disruptive; do last, after content is stable)
66. Add a size-guard CI check (block new blobs > N MB) — **prevents recurrence before** any purge.
67. Document the history-purge plan for the 56 MB / 24 MB / 5.3 MB blobs still in history (#222) + a coordinated re-clone window.
68. Execute the `git filter-repo` purge in the agreed window — depends on 66–67. **(big-diff / history rewrite)**
69. Verify post-purge clone size and update `RECOMMENDATIONS.md` #1 + this doc — depends on 68.

## WAVE M — Runtime robustness & resumption readiness (the project is paused pending sources)
_Capstone: make resuming ingestion safe and observable._

70. Introduce structured logging across `contract_sweeper/runtime/` (replace bare prints) — improves resumption debuggability.
71. Add jitter/backoff + circuit-breaker tests around `retry_runtime` — depends on 37.
72. Add a diagnostic-mode smoke CI job that dry-runs the `run_all` orchestration — catches integration breakage before source delivery.
73. Add contract tests asserting the 56 `NotImplementedAdapter` stubs stay deferred (no accidental activation).
74. Tie a resumption checklist into `production-status-gate.yml` so `NON_PRODUCTION_DIAGNOSTIC` can only flip when source preflight passes.
75. Build one end-to-end golden-path test for a fully-implemented source as the **template** the remaining sources are onboarded against — the capstone that scales source delivery.

---

### Critical-path summary
`A (tooling) → B (lint clean) → C (format) → D (types) → F (coverage baseline) → G (tests)`
is the spine: each flips a gate green only after the code can pass it. **E** (contracts),
**H** (deps), **I** (governance), **J** (release) are largely independent and can be
interleaved by a second contributor without blocking the spine. **L** (history rewrite) and
**M** (resumption) are deliberately last — L because it's disruptive, M because it depends on
a clean, well-gated, well-tested build being in place first.
