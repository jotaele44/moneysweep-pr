# Contract-Sweeper — Improvement Recommendations

_Generated 2026-05-29. Advisory only — no source code was refactored or deleted
in the change that introduced this document. Each item below is sized so the
maintainer can approve the higher-risk moves (git-history rewrite, large
refactors) deliberately._

## Snapshot

| Metric | Value |
|--------|-------|
| Python files | ~410 |
| Python LOC | ~100k |
| `scripts/` files | 158 (69 are `download_*.py`) |
| `contract_sweeper/pipeline/` files | ~42 |
| Test files | 106 |
| Data committed to git | ~89 MB under `data/` |
| Largest single source file | `run_all.py` (114 KB) |
| CI workflows | 6 |
| Pre-commit | yes |

**Strengths to preserve:** strong test suite (106 files), pre-commit config, six
CI workflows, a tests badge, and a clearly documented pipeline in the README.
The recommendations below are about taming accreted scale, not rescuing a
struggling project.

## Priority matrix

| # | Area | Issue | Recommendation | Effort | Risk | Priority |
|---|------|-------|----------------|--------|------|----------|
| 1 | Remove | ~89 MB of data blobs committed to git (56 MB `data/raw/Follow the Money/funding_flows_sf133.csv`, 24 MB `data/staging/processed/partial/..._r4_9g.csv`, 5.3 MB FEC CSV, several PDFs) | Purge from history with `git filter-repo`; move sample data to release assets / external object storage | M | High (history rewrite) | P0 |
| 2 | Improve | `.gitignore` claims data is "too large for git" but blobs slipped through because their paths don't match the globs (spaces, nested dirs) | Switch to a deny-all `data/**` rule with an explicit `!*.gitkeep` / `!manifest.json` allowlist | S | Low | P0 |
| 3 | Reorganize | Pipeline-script graveyard: ~42 files in `contract_sweeper/pipeline/`, many one-off remediation passes (`backfill_failure_remediation`, `controlled_backfill_execution`, `final_backfill_retry`, `targeted_backfill_retry`, `partial_master_rebuild`, `scoped_partial_rebuild`, `final_source_recovery_pass`, `producer_patch_retry`, `endpoint_patch_retry`, …) | Move superseded one-shots into `archive/` (precedent: `archive/r4_legacy/`); keep only the current canonical backfill path | M | Medium | P1 |
| 4 | Reorganize | 69 `download_*.py` scripts with no shared base — high duplication of fetch/retry/validate/manifest logic | Extract a `BaseDownloader` (or `acquisition` module) handling HTTP, retry, checksum, manifest write; make each source a thin subclass/config | L | Medium | P1 |
| 5 | Improve | `run_all.py` is a single 114 KB monolithic orchestrator | Decompose into a thin CLI entry + per-stage modules (one module per the 7 documented steps) | L | Medium | P1 |
| 6 | Improve | Round-suffixed test names (`test_*_r48b`, `_r49z`, `_r48d`) are hard to navigate and imply ad-hoc development rounds | Rename to describe behavior under test; drop round suffixes | S | Low | P2 |
| 7 | Remove | Data paths with spaces / trailing spaces (`data/raw/Follow the Money/`, `data/raw/Torres-Rosa Consultation /`) are fragile in shell/CI | Normalize to snake_case directory names | S | Low | P2 |
| 8 | Upgrade | No static type checking; deps are floor-pinned only (`>=`) with no lockfile | Add `mypy` to pre-commit + CI (start in non-blocking mode); add a lockfile (`pip-tools`/`uv`) for reproducible installs | M | Low | P2 |

## Quick wins (low effort, low risk)

- **#2** Tighten `.gitignore` to `data/**` + allowlist (prevents *new* blobs even before the history purge).
- **#6** Rename round-suffixed tests.
- **#7** Normalize directory names containing spaces.

## Larger initiatives (plan + sign-off)

- **#1 git-history purge** — the single biggest clone-size win. Requires a
  coordinated force-push and everyone re-cloning; do it when the team can absorb
  the disruption. Pair it with **#2** so blobs don't creep back.
- **#4 / #5 acquisition + orchestrator refactor** — these are the structural
  changes that make the codebase navigable again. Tackle after the pipeline
  graveyard (#3) is archived so you refactor only live code.

## Cross-repo federation (shared with spiderweb-pr)

Contract-Sweeper produces a versioned "Contract-Finance" export contract
(currently v1.2.0) consumed by `spiderweb-pr`'s federation adapter. The version
is bumped by hand across both repos. **Recommendation:** add an automated
contract-compatibility test — a golden schema fixture plus an explicit version
assertion — in both repos so a producer-side change can't silently diverge from
the consumer. This is the highest-leverage cross-cutting improvement because it
protects the integration boundary that both projects depend on.
