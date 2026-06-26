# moneysweep-pr — Codebase Consistency Audit

_Generated 2026-06-06. Reconcile-and-extend over [RECOMMENDATIONS.md](../RECOMMENDATIONS.md)._

## Method

This is a **drift audit**: for each layer, characterize the canonical pattern,
then count how many instances diverge. All counts were recomputed from the live
tree on 2026-06-06; the figures in [RECOMMENDATIONS.md](../RECOMMENDATIONS.md)
(dated 2026-05-29) and [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) (R5) are
already stale and were not reused for quantitative claims.

## Snapshot vs. last audit (2026-05-29 → 2026-06-06)

| Metric | RECS / ARCH | Now | Δ |
|---|---|---|---|
| `download_*.py` | 69 / 74 | **70** | +1 |
| Total `scripts/*.py` | 158 / 165 | **199** | +34 |
| `ingest_*.py` | — / 11 | **23** | +12 |
| `moneysweep/pipeline/` files | ~42 | **42** | 0 |
| `tests/test_*.py` | 106 | **161** | +55 |
| `docs/*.md` | — | **56** (top level) | — |
| `reports/` artifacts | — | **38** | — |
| `schemas/*.schema.json` | — | **27** | — |
| `scripts/config.py` inbound imports | 121 | **128** | +7 |
| `run_all.py` | 114 KB / 1 file | 90 KB / **1857 LOC** | -24 KB |

The codebase grew by ~25% in script count and ~50% in test count in one week,
while the structural debt items from RECOMMENDATIONS.md only partially landed.

## Reconcile with RECOMMENDATIONS.md (2026-05-29)

| # | RECS item | Status | Evidence |
|---|---|---|---|
| 1 | Purge ~89 MB data blobs from git history | **Open** | `git ls-files data/raw/follow_the_money/` returns 5+ tracked CSVs (`EP_PR_PRBank_Summary_ByAccount.csv`, `..._ByEntity.csv`, `..._ByYear.csv`, `..._Wire_Ledger_ALL.csv`, `Municipal_Blind_Score_CORE6.csv`). History rewrite not done. |
| 2 | Tighten `.gitignore` to `data/**` allowlist | **Open** | `.gitignore` still uses path-by-path globs (`data/staging/processed/**`, `data/staging/raw/**/*.csv`, `data/raw/*.csv`, plus explicit named files), not the deny-all `data/**` + allowlist form RECS proposed. |
| 3 | Archive `moneysweep/pipeline/` one-shots | **Open** | Still 42 files; all `backfill_*`, `*_retry`, `partial_*_rebuild` files remain. |
| 4 | Extract `BaseDownloader` | **Partial** | PR [#201](https://github.com/jotaele44/moneysweep-pr/pull/201) shipped + migrated 10. **60 downloaders still hand-rolled** (see Downloader Drift below). |
| 5 | Decompose `run_all.py` | **Partial** | PR [#202](https://github.com/jotaele44/moneysweep-pr/pull/202) extracted CLI (16.7 KB) and support (7.7 KB) into `moneysweep/orchestrator/`. `run_all.py` is still **1857 LOC / 90 KB** — most of the body is unmoved. |
| 6 | Rename round-suffixed tests | **Open** | 19 tests still match `test_*_r4[0-9][a-z]*.py`. |
| 7 | Normalize space-named data dirs to snake_case | **Done** | PR [#200](https://github.com/jotaele44/moneysweep-pr/pull/200) (commit `75b276b` cites "RECOMMENDATIONS #7" in its message). |
| 8 | Add mypy + lockfile | **Partial** | `requirements.lock` present (new since RECS). `.pre-commit-config.yaml` was read directly: only `gitleaks` and `detect-private-key` hooks configured; no `mypy`. |

## Downloader Drift (the load-bearing finding)

The canonical pattern is `moneysweep/runtime/base_downloader.py` —
`HttpConfig` dataclass, `build_session`, `http_get_json` / `http_post_json` with
the unified retry policy, `paginate`, `file_has_data`, `write_csv`, and the
`BaseDownloader` class that wires them. Counts:

| Measure | Count | % | Notes |
|---|---|---|---|
| `scripts/download_*.py` total | **70** | 100% | canonical denominator |
| Use `BaseDownloader` or `base_downloader` | **10** | **14.3%** | The 10 migrated in PR #201 (`doj_grants`, `ed`, `epa`, `fdic`, `fec`, `lda`, `hhs`, `haf`, `oia`, `usace_civil`). |
| Define local retry constants (`MAX_RETRIES`, `RETRY_SLEEP`, `RETRY_BACKOFF`) | **66** | 94% | Arithmetic: 60 unmigrated + ≥6 migrated still carry legacy constants — even the PR #201 migration is partial per-file. |
| Define a `_get_with_retry`-style local function | **2** | 3% | (`fema`, one other) — most use inline retry, not a named helper. |
| `import requests` directly (rather than via `BaseDownloader.session`) | **68** | 97% | Same as above — direct `requests` survives in migrated wrappers too. |
| Duplicate `from __future__ import annotations` (copy-paste bug) | **1** | — | `scripts/download_emma.py` lines 17 + 19. Real bug. |

### What the 60 non-migrated downloaders do that BaseDownloader already covers

Sampling `download_fema.py` and `download_emma.py` (representative
non-migrated):

- Both define their own `PAGE_SIZE`, `PAGE_SLEEP` / `SLEEP_BETWEEN_PAGES`,
  `MAX_RETRIES` / `RETRY_SLEEP`, with values that vary by source — same concept,
  ~70 different magic numbers. `HttpConfig` is designed to be those exact knobs.
- `download_fema.py` rolls its own `_get_with_retry` (2-attempt fixed sleep on
  429/503). `BaseDownloader.get` already handles 429 with `rate_limit_sleep`,
  4xx as terminal, 5xx/transport as retry — and uses `with_retry` + `RetryPolicy`
  rather than an ad-hoc list.
- `download_fema.py` defines local `STAGING_RAW_DIR`, `PA_RAW_DIR`, etc. —
  `BaseDownloader.raw_dir` and `processed_dir` already standardize these.
- `download_emma.py` ships a hard-coded `KNOWN_EMMA_BONDS` fallback list inside
  the downloader. That's not a BaseDownloader concern; it's a data-provenance
  concern (see Lineage finding below).

### Recommendation

A second BaseDownloader migration wave — 60 files, ~2-4 hours/file at the
current size — would push adoption from 14% → 100%. Most of the work is
mechanical: replace the local `_get_with_retry` + constants with `HttpConfig` +
`super().get`. Track adoption % as a CI metric so newly-added downloaders
default to the base.

## Schema / Registry Drift

### Schemas

`schemas/*.schema.json` — **27 files**, all snake_case, all `.schema.json`
suffix. **Naming convention is consistent.** One drift:

| Issue | Count |
|---|---|
| `moneysweep_*` prefix | 6 / 27 (22%) |
| No prefix | 21 / 27 (78%) |

The 6 prefixed schemas (`entity`, `export_manifest`, `funding_award`,
`relationship`, `source`, `transaction`) look like the "core canonical contract"
that ships to downstream consumers (e.g., spiderweb-pr); the rest are
internal/derived schemas. The prefix carries meaning but it's undocumented.
**Recommendation:** document the prefix as the "exported canonical" marker, or
drop it and use a directory split (`schemas/canonical/`, `schemas/internal/`).

A `schemas/canonical_v1/` directory also exists — version-in-directory rather
than version-in-filename. Compare with the README's mention of "Contract-Finance
export contract v1.2.0": the version exists in two places (export contract
version, schema directory) with no clear coupling.

### Registries

Both **`.json` and `.yaml`** of every registry are committed:

| Registry | .json | .yaml | Drift risk |
|---|---|---|---|
| `source_registry` | 46.7 KB | 40.1 KB | High |
| `schema_registry` | 32.5 KB | 24.3 KB | High |
| `endpoint_candidates` | 9.4 KB | 8.3 KB | Medium |
| `manual_export_registry` | 4.4 KB | 3.7 KB | Medium |

That's ~125 KB of duplicated configuration. Nothing in the audit identifies
which is the source of truth, what regenerates the other, or whether they're
allowed to drift. This is a classic "two registries → one will quietly become
wrong" pattern. **Recommendation:** pick one canonical format (YAML for
human-edited, JSON for machine outputs), generate the other from it, and add a
CI check that they are in sync. If both are hand-edited, expect silent drift.

## Orchestration & Config Drift

### `run_all.py`

PR [#202](https://github.com/jotaele44/moneysweep-pr/pull/202) extracted the
CLI parser and support helpers into `moneysweep/orchestrator/`:

```
moneysweep/orchestrator/__init__.py    (89 B)
moneysweep/orchestrator/cli.py         (16.7 KB)
moneysweep/orchestrator/support.py     (7.7 KB)
```

`run_all.py` itself is still **1857 LOC / 90 KB** — the bulk of the orchestrator
body (per-stage runners, the 8-step pipeline from
[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md#data-flow)) has not yet moved.
The README's docstring says the package is for "thin CLI + support helpers +
(future) per-stage modules" — the "future" is the open work. The original
RECOMMENDATIONS #5 ask was "one module per documented step"; the per-stage
extraction remains.

### `scripts/config.py` — central singleton

128 inbound imports (up from 121 in RECS), making it the most-imported module
in the project by a wide margin. This is fine if it stays small and stable, but
it's a strong coupling surface — any rename in `config.py` requires touching
128 files. **Recommendation:** treat `scripts/config.py` as a public contract,
document it as such, and add a docstring at the top warning maintainers not to
rename exported symbols without a coordinated sweep.

### CLI flag consistency

`run_all.py` defines 8+ documented flags (`--only-setup`, `--skip-download`,
`--manual-only`, `--force-download`, `--skip-validation`, `--skip-normalize`,
`--skip-dedup`, `--skip-coverage`, `--skip-enrichment`, `--strict-preflight`).
Convention is `--skip-X` for stage skip. Exception: `--manual-only` is documented
as "Alias for `--skip-download`" — the alias is fine but the convention break
is worth a deprecation note.

## Naming, Tests, and Structural Debt

### Round-suffixed tests (RECS #6, still open)

**19 files** match `test_*_r4[0-9][a-z]*.py`:

```
test_backfill_failure_remediation_r48c.py
test_backfill_readiness_audit_r48a.py
test_backfill_runner_r47.py
test_controlled_backfill_r48.py
test_external_blocker_freeze_r49d.py
test_external_source_delivery_gate_r49c.py
test_final_source_recovery_pass_r48i.py
test_manual_fulfillment_endpoint_retry_r48h.py
test_raw_usaspending_discovery_r49h.py
test_raw_usaspending_mapping_feasibility_r49h2.py
(+ 9 more)
```

These read as "test for the thing that was added in rebuild round 4.8c", which
is meaningful at the time and meaningless six months later. Drop the suffix and
rename to the behavior under test.

### `moneysweep/pipeline/` — the graveyard (RECS #3, still open)

42 files, of which the following are visibly one-shot remediation passes:

```
backfill_failure_remediation.py
backfill_readiness_audit.py
backfill_runner.py
controlled_backfill.py
controlled_backfill_execution.py
endpoint_patch_retry.py
final_backfill_retry.py
final_source_recovery_pass.py
partial_master_rebuild.py
partial_rebuild_gate.py
partial_rebuild_retry.py
producer_patch_retry.py
scoped_partial_rebuild.py
source_recovery_pause_lock.py
targeted_backfill_retry.py
```

That's **15 of 42** with names that imply a specific rebuild round. The naming
itself is the smell: the existence of "final_backfill_retry", "partial_rebuild_retry",
and "targeted_backfill_retry" together suggests the "final" wasn't.
**Recommendation:** archive to `archive/r4_pipeline_legacy/` (mirror the existing
`archive/r4_legacy/` precedent), leave a tombstone README in `pipeline/`.

### `docs/` and `reports/` proliferation

- `docs/`: **56 markdown files** at the top level, 3 subdirectories. The
  README points to 5 canonical docs (`ARCHITECTURE`, `DATA_POLICY`,
  `MATERIALIZATION_RUNBOOK`, `MODULE_REDUCTION_PLAN`, `NGO_INTEGRATION`); the
  other 51 are runbooks, handoffs, and per-round status reports.
- `reports/`: **38 files** mixing machine-readable status (`current_status.json`,
  `materialization_readiness.json`, `source_registry_status.csv`) with audit
  artifacts and ad-hoc analyses.

Neither directory has a stated convention for what belongs there. The
`docs/MODULE_REDUCTION_PLAN.md` doc-vs-reality drift is a finding in itself —
the plan describes a target directory structure (`sources/`, `ingest/`,
`normalize/`, etc.) that, per ARCHITECTURE.md R5, is "not started" but appears
to remain the official target.

**Recommendation:** split `docs/` into `docs/architecture/` (current),
`docs/runbooks/` (operational), and `docs/history/` (handoffs, past-round
status). Same split for `reports/` — current status vs historical snapshots.

### `ingest_*.py` — the next refactor surface

23 files (grew from 11 in ARCHITECTURE.md). **Zero** use a shared base class —
there is no `BaseIngester` yet. They're roughly the same shape: read a raw CSV,
apply a column mapper, write to `processed/pr_*.csv`. This is the same
duplication pattern downloaders had before BaseDownloader. The lesson from #201
is that extracting the base is straightforward; the work is in migrating. If
the team plans more ingesters, do the extraction now while there are 23, not
later at 60.

## Priority Actions (drift-weighted)

| # | Action | Drift metric it closes | Effort | Risk |
|---|---|---|---|---|
| 1 | Migrate remaining 60 downloaders to `BaseDownloader` | 14% → 100% adoption; eliminates 66 hand-rolled retry constants | L | M |
| 2 | Pick a canonical registry format (JSON or YAML) and generate the other | ~125 KB duplication; silent drift surface | S | L |
| 3 | Archive 15 `pipeline/` one-shot files to `archive/r4_pipeline_legacy/` | 42 → ~27 files in `pipeline/` | S | L |
| 4 | Rename 19 round-suffixed tests | 19 → 0 | S | L |
| 5 | Fix `download_emma.py` duplicate `__future__` import | 1 real bug | XS | L |
| 6 | Extract a `BaseIngester` from the 23 `ingest_*.py` files | 0% → ≥50% adoption pre-emptively | M | M |
| 7 | Complete `run_all.py` decomposition: extract per-stage modules | 1857 → ~300 LOC in `run_all.py` | M | M |
| 8 | Document the `moneysweep_*` schema prefix as a marker, or remove it | 22% prefixed schemas → consistent rule | S | L |
| 9 | Split `docs/` and `reports/` by category | 56 + 38 flat files → categorized | S | L |
| 10 | Add `mypy` to pre-commit (non-blocking start) | RECS #8 part-2 | S | L |

## What's already healthy

- **Schema file naming** — 27 files, all snake_case, all `.schema.json` suffix.
- **Snake_case data dir rename** — RECS #7 shipped cleanly in PR #200.
- **BaseDownloader design** — the canonical pattern is well-factored (functional
  core + OO wrapper, retry policy in `retry_runtime`, pagination in
  `pagination_runtime`). The pattern itself is solid; only adoption is partial.
- **Test count growth** — 106 → 161 tests in one week is real coverage, not
  test inflation.
- **Lockfile** — `requirements.lock` shipped (RECS #8 part-1).
- **CLI flag convention** — `--skip-X` per stage is consistent.
