# Contract-Sweeper — Code Gap Analysis & Repo Workflow Audit

> **⚠️ Retired (2026-06-16).** Every finding in this audit (A1, A2/B5, A3, B1, B2, B3,
> B4, B6) has been resolved or mitigated on `main`. Now in place: the quality-gate spine
> (`ruff` + `mypy` gating, `pytest --cov-fail-under`), governance files (CONTRIBUTING /
> CODE_OF_CONDUCT / LICENSE / CODEOWNERS / PR template), `.github/dependabot.yml`,
> `CHANGELOG.md` + `.github/workflows/release-tag.yml`, the narrowed `except` in
> `contract_sweeper/runtime/validation_gates.py`, and the large-blob posture
> (`docs/HISTORY_PURGE_PLAN.md` + `.github/workflows/size-guard.yml`). This file is
> retained for historical reference only — see `CHANGELOG.md` and
> `docs/BUILD_EXECUTION_SEQUENCE.md` (Waves A–M) for the authoritative record. Tracked by #260.

_Generated 2026-06-08. **Advisory only** — no source code, configuration, or
workflow was changed by the commit that introduced this document (same posture as
`RECOMMENDATIONS.md` and `docs/DEPENDENCY_SECURITY_AUDIT.md`). Each finding below is
sized so the maintainer can approve higher-risk moves deliberately, consistent with
the repo's `no_broad_audits_without_approval` / `delta_only_reporting` controls in
`reports/current_status.json`._

This audit is a **code/engineering** gap analysis. It is distinct from
`scripts/gap_analysis_builder.py`, which is a **data-materialization** gap tool
(declared vs. materialized source outputs in `reports/gap_analysis_report.*`).

## Snapshot (verified 2026-06-08)

| Metric | Value |
|--------|-------|
| Source modules (`contract_sweeper/`) | ~84 |
| `contract_sweeper/pipeline/` modules | 28 |
| `contract_sweeper/query/adapters/` modules | 21 |
| Test files (`tests/`) | 154 |
| Last full suite | 1229 passed · 5 skipped · 0 failed (2026-06-01) |
| CI workflows (`.github/workflows/`) | 11 |
| Git tags / releases | 0 |
| Tracked bytes under `data/` | ~12 MB (was ~89 MB; large blobs since pruned from working tree) |
| Packed `.git` | ~11 MB |
| Production status | `NON_PRODUCTION_DIAGNOSTIC` (paused pending source delivery) |

**Strengths to preserve:** large green test suite, 11 CI workflows (incl. a
promotion guard and production-status gate), a registry-first architecture, a
pre-commit config with secrets scanning, mypy wired in, issue templates, and
extensive runbooks. The findings below are about closing coverage and
process gaps, not rescuing a struggling project.

**Already actioned (do not re-raise)** — landed via the "Audit Phase 1/2/3" and
"queue" PRs: test renames + mypy pre-commit hook + `.gitignore` tighten (#206),
YAML-as-truth guardrails (#209), R4 pipeline-graveyard archival (#208),
`BaseDownloader` extraction (#201/#204), `run_all.py` decomposition (#202),
space-named-dir normalization (#200). A `requirements.lock` is present.

---

## A. Code gap analysis

### A1 — Test coverage skewed away from security-sensitive code (priority: high)
The suite is large but concentrated in registry/gate/export logic. The
credential- and filesystem-handling surface is thin on direct tests:

- **Pipeline: ~3 of 28 modules have dedicated tests.** Untested, high-risk modules:
  - `contract_sweeper/pipeline/credentialed_endpoint_execution.py` (547 LOC) — handles API credentials/endpoints
  - `contract_sweeper/pipeline/manual_import_dropzone.py` (459 LOC) — ingests operator-supplied files
  - `contract_sweeper/pipeline/source_materialization.py` (408 LOC)
  - `contract_sweeper/pipeline/scoped_unfreeze_materialization.py` (435 LOC)
- **Query adapters: 4 adapter test files** (`test_query_adapters.py`,
  `test_query_adapters_benefits.py`, `test_query_adapters_cms.py`,
  `test_query_entity_adapters.py`) cover a subset of the 21 adapters. External-API
  adapters such as `sam.py`, `highergov.py`, `ckan_metastore.py`, `cms_socrata.py`,
  and `ofac.py` lack dedicated error-path/credential-path tests.
- **Runtime helpers with no dedicated test:** `retry_runtime.py`,
  `pagination_runtime.py`, `file_hash_runtime.py`, `evidence_tiers.py`,
  `risk_signal_gates.py` — these govern retry/pagination/hashing behavior on
  external calls and are good candidates for fast unit tests.

_Recommendation:_ prioritize unit tests (with mocked HTTP/credentials) for the
credentialed/manual-import/materialization modules first, then the external-API
adapters. These are the paths where an untested edge case has real blast radius.

### A2 — No linter/formatter; mypy is report-only and narrow (priority: medium)
- No `ruff`/`flake8`/`black`/`isort` config anywhere; style/lint is unenforced.
- `mypy` runs in CI but as a **non-gating** check (`.github/workflows/mypy.yml`
  sets `continue-on-error: true`), and the pre-commit mypy hook is scoped to
  `contract_sweeper/runtime/` only — `scripts/`, `tests/`, and `pipeline/` are
  excluded (`pyproject.toml` `exclude = "(^archive/|^scripts/|tests/)"`).
- `pytest-cov` is configured (`pytest.ini`) but there is **no coverage threshold
  gate** (`--cov-fail-under`), so coverage can regress silently.

_Recommendation:_ add `ruff` (lint + format) to pre-commit and CI; once the mypy
baseline is clean, flip `mypy.yml` to gating and widen scope; add a modest
`--cov-fail-under` floor to lock in current coverage.

### A3 — Broad exception swallowing in a shared helper (priority: low)
`contract_sweeper/runtime/validation_gates.py` (~lines 76–80) reads CSVs under a
bare `except Exception: return []`. A malformed/locked file is indistinguishable
from an empty one, which can let a validation gate pass on absent data.

_Recommendation:_ narrow to the expected I/O/parse exceptions and log the cause.

### A4 — Intentional stubs (documented as **known**, not defects)
Recorded here so they are not mistaken for gaps:
- NARA NextGen / NARA v3 are `deferred_stub` (awaiting credential/allowlist);
  `scripts/download_nara_nextgen.py` is a deliberate no-op so strict preflight passes.
- 56 of the registered sources fall back to `contract_sweeper/query/adapters/_stub.py`
  (`NotImplementedAdapter`) for on-demand `.query()`; the production pipeline is unaffected.
- `scripts/enrichment/enrich_financialdata_entities.py:284` — live mode is an
  intentional deferred stub.

---

## B. Repository workflow audit

### B1 — Finance-lane report is unschematized (priority: medium) — _corrected 2026-06-08_
> **Correction.** An earlier draft of this audit (and tracking issue #216) framed the
> two `EXPORT_CONTRACT_VERSION` constants as a single contract that had "drifted." That
> was wrong, and closer reading proves it. The two constants version **two independent
> cross-repo contracts**, so they legitimately differ:
> - `scripts/build_export_package.py:33` → `1.2.0` — the **federation export package
>   manifest** (entities/sources/funding_awards/transactions/relationships → `spiderweb-pr`
>   query-hub). Validated by `schemas/contract_sweeper_export_manifest.schema.json`
>   (`const: "1.2.0"`) and asserted in `tests/test_run_export.py`.
> - `readiness/contract_sweeper_finance_lane.py:28` → `1.0.0` — the **PR-intake finance
>   lane** (issue #114), a different boundary that consumes `contract_sweeper_derivatives.csv`
>   and emits its own report (`contract_sweeper_finance_lane_report.json`,
>   `"producer": "pr-intake-router"`). It never references the federation manifest schema.
>
> Forcing the finance lane to `1.2.0` would therefore have **corrupted a correct version**.
> #216 is closed as a false positive.

The **real, smaller** residual gap: the finance-lane report has **no JSON Schema** and no
test validating its shape/version, whereas the federation package does. _Recommendation:_
add `schemas/contract_sweeper_finance_lane_report.schema.json` + a test that validates the
emitted report and asserts `export_contract_version == "1.0.0"`, and add a one-line
provenance comment at each constant naming which contract it versions (so the two are never
again mistaken for one). Tracked as WAVE E in `docs/BUILD_EXECUTION_SEQUENCE.md`.

### B2 — Missing governance / community files (priority: medium)
Absent: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `LICENSE`, `CODEOWNERS`, and a PR
template (`.github/pull_request_template.md`). Issue templates **are** present
(`.github/ISSUE_TEMPLATE/`). The lack of a `LICENSE` is notable for a repo that
ingests/redistributes public data; `CODEOWNERS` + a PR template would reinforce the
Architect-gate workflow the repo already operates under informally.

### B3 — No automated dependency / security updates (priority: medium)
No `.github/dependabot.yml`. Dependencies are floor-pinned (`>=`) in
`requirements.txt` with a `requirements.lock` present, but nothing surfaces new CVEs
or version bumps. _Recommendation:_ add `dependabot.yml` (pip + github-actions
ecosystems), weekly cadence.

### B4 — No release / versioning process (priority: medium)
Zero git tags, no `CHANGELOG.md`, no release automation — despite the repo shipping a
versioned export contract consumed by another repo. _Recommendation:_ adopt
lightweight tagging tied to `export_contract_version`, with a `CHANGELOG.md` so the
`spiderweb-pr` consumer can track breaking contract changes.

### B5 — Lint absent from CI; mypy non-gating (priority: medium)
CI is otherwise strong (`ci.yml`, `tests.yml` py3.10–3.12 matrix, `promotion-guard`,
`production-status-gate`, `registry-sync`, `repro`). Adding a lint job and promoting
mypy to gating (see A2) would round out the quality gates. Tracked under A2.

### B6 — Large blobs remain in git history (priority: low — **downgraded**)
The ~89 MB figure in `RECOMMENDATIONS.md` #1 is **stale**: the working tree now
tracks only ~12 MB under `data/`. The large objects (56 MB
`data/raw/.../funding_flows_sf133.csv`, 24 MB partial diagnostic CSV, 5.3 MB FEC
CSV) still exist **in history**, but compress to a ~11 MB packed `.git`, so clone
cost is modest. A `git filter-repo` purge is still the cleanest long-term fix but is
**not** the P0 the stale doc implies; weigh it against the disruption of a coordinated
history rewrite.

---

## Priority summary

| Pri | ID | Finding | Area |
|-----|----|---------|------|
| High | A1 | Test security-sensitive untested pipeline modules + external-API adapters | tests |
| ~~High~~ Med | B1 | ~~Version drift~~ **(corrected)** — two independent contracts; real gap is the unschematized finance-lane report | cross-repo |
| Medium | A2/B5 | Add lint (ruff); make mypy gating + widen scope; add coverage floor | tooling/CI |
| Medium | B2 | Add governance files (CONTRIBUTING, CODEOWNERS, LICENSE, PR template) | workflow |
| Medium | B3 | Add `dependabot.yml` for dependency/security updates | workflow |
| Medium | B4 | Add release/versioning + `CHANGELOG.md` tied to export contract | workflow |
| Low | A3 | Narrow broad `except Exception` in `validation_gates.py` | robustness |
| Low | B6 | (Optional) purge large blobs from git history — modest, not P0 | repo size |

## Related documents
- `RECOMMENDATIONS.md` — prior advisory matrix (several items since actioned; #1 figure now stale; cross-repo item refined by B1 here).
- `docs/MODULE_REDUCTION_PLAN.md` / `docs/MODULE_CONSOLIDATION_SCOPE.md` — consolidation roadmap (#69).
- `docs/DEPENDENCY_SECURITY_AUDIT.md` — dependency posture.
- `reports/current_status.json` — machine-readable source of truth for operating state.
