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

7. Apply `ruff check --fix` safe autofixes (≈263: F401 unused-import ×211, F541 f-string ×52). Mechanical. **(big-diff)**
8. Resolve remaining **F841** unused-variable (≈34) by hand — not auto-fixed.
9. Resolve **E402** module-import-not-at-top (≈26) — add scoped `# noqa: E402` only where a sys.path shim is genuinely required, fix the rest.
10. Resolve **E701/E702** multiple-statements-on-one-line (≈18) — split.
11. Resolve **E712/E731/E741** (≈9) — `== True` → truthiness, named funcs over lambdas, rename ambiguous `l/O/I`.
12. Re-run `ruff check .` → confirm 0 errors (or a small, commented `noqa` set).
13. **(gate)** Flip the ruff lint CI job to blocking (remove `continue-on-error`). Safe only because 12 is clean.

## WAVE C — Formatting (isolated; do after lint so the two don't interleave)
_`ruff format` rewrites 507 files. Keep it surgical and reviewable._

14. Decide & document the format-adoption strategy (one big-bang vs. dir-by-dir) in this file. Prerequisite for 15.
15. Apply `ruff format .` in a **dedicated PR**, formatting only — no logic changes. **(big-diff)**
16. Add the format-changing commit SHA to `.git-blame-ignore-revs` so blame stays readable.
17. **(gate)** Add ruff-format pre-commit hook + gating `ruff format --check` CI step — depends on 15.

## WAVE D — Type-safety hardening (after lint/format; mypy widening)
_Each step keeps the existing narrow mypy gate green while widening it._

18. Fix the known `geo_attribution.py:173` dict-item return-type bug (already flagged in `.pre-commit-config.yaml`).
19. Remove the `geo_attribution.py` exclude from the mypy pre-commit hook — depends on 18.
20. Annotate public signatures in `contract_sweeper/pipeline/*.py`. Prerequisite for 22.
21. Annotate public signatures in `contract_sweeper/query/adapters/*.py`.
22. Widen mypy `files` in `pyproject.toml` from `contract_sweeper` (runtime-focused) to include `pipeline/` + `query/` — depends on 20–21.
23. Add `types-requests` / `pandas-stubs` and start dropping `ignore_missing_imports` per-module.
24. Bring `scripts/` into mypy scope (currently excluded) — depends on annotations + 4.
25. **(gate)** Flip `.github/workflows/mypy.yml` from `continue-on-error: true` to blocking — depends on a clean baseline across 18–24.

## WAVE E — Cross-repo contract hardening (corrects the #216 false positive)
_See `docs/CODE_GAP_AND_WORKFLOW_AUDIT.md` §B1 correction._

26. Add a one-line provenance comment at **each** `EXPORT_CONTRACT_VERSION` (federation package vs. finance lane) so the two contracts are never conflated again.
27. Author `schemas/contract_sweeper_finance_lane_report.schema.json` for the finance-lane report — the real B1 gap.
28. Add a test validating an emitted finance-lane report against schema 27 and asserting `export_contract_version == "1.0.0"` — depends on 27.
29. Add a conformance-fixture freshness check for `exports/conformance/v1_2/` so the federation package can't silently drift from its schema.
30. Centralize each contract version into a single importable constant (one per contract) — removes the duplicate literal in `scripts/build_export_package.py` vs. samples.

## WAVE F — Coverage instrumentation (before adding the floor, measure)
_Set the ratchet only after you know the number it should start at._

31. Make the CI test job print the total coverage % and keep `coverage.xml` as an artifact (already uploaded) — establishes the baseline.
32. **(gate)** Add `--cov-fail-under=<measured baseline>` to `pytest.ini` — locks coverage; depends on 31.

## WAVE G — Tests for untested critical paths (#215; ratchet coverage as you go)
_Highest-blast-radius modules first. Each new test file lets you raise the floor._

33. Unit-test `contract_sweeper/pipeline/credentialed_endpoint_execution.py` (mock HTTP + credentials).
34. Unit-test `contract_sweeper/pipeline/manual_import_dropzone.py` (operator-supplied file ingestion).
35. Unit-test `contract_sweeper/pipeline/source_materialization.py`.
36. Unit-test `contract_sweeper/pipeline/scoped_unfreeze_materialization.py`.
37. Unit-test `contract_sweeper/runtime/retry_runtime.py`.
38. Unit-test `contract_sweeper/runtime/pagination_runtime.py`.
39. Unit-test `contract_sweeper/runtime/file_hash_runtime.py`.
40. Unit-test `contract_sweeper/runtime/evidence_tiers.py`.
41. Unit-test `contract_sweeper/runtime/risk_signal_gates.py`.
42. Adapter error/credential-path tests: `query/adapters/sam.py`.
43. Adapter error/credential-path tests: `query/adapters/highergov.py`.
44. Adapter error/credential-path tests: `query/adapters/ckan_metastore.py`.
45. Adapter error/credential-path tests: `query/adapters/cms_socrata.py`.
46. Adapter error/credential-path tests: `query/adapters/ofac.py`.
47. Narrow the broad `except Exception: return []` in `runtime/validation_gates.py` (#221) + add a malformed-file regression test — safe now that the path is covered.
48. **(gate)** Raise `--cov-fail-under` to the new, higher post-33–47 baseline — ratchet up.

## WAVE H — Dependency & supply-chain automation (after dev-deps exist)
49. Add `.github/dependabot.yml` (`pip` + `github-actions`, weekly) — #219; depends on 4.
50. Add a CI check that `requirements.lock` is in sync with `requirements.txt` (fails on drift).
51. Adopt `pip-tools` (or `uv`) to regenerate `requirements.lock` deterministically — depends on 50.
52. Add a scheduled `pip-audit` CI job — operationalizes `docs/DEPENDENCY_SECURITY_AUDIT.md`.

## WAVE I — Governance & community scaffolding (independent; low coupling)
53. Add `LICENSE` (select a license suited to public-data redistribution) — #218.
54. Add `CONTRIBUTING.md` documenting the branch/PR flow **and** the now-green quality gates (Waves A–G).
55. Add `CODEOWNERS` reflecting the Architect-gate ownership the repo already runs informally.
56. Add `.github/pull_request_template.md` mirroring the existing review checklist.
57. Add `CODE_OF_CONDUCT.md`.
58. Add `SECURITY.md` (disclosure policy) — pairs with dependabot/pip-audit.

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
