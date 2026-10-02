# Contributing to moneysweep-pr

Thanks for helping improve moneysweep-pr — a pipeline for tracing Puerto Rico
public money across federal and local sources. This guide covers the workflow and
the automated quality gates every change must pass.

## Operating model

The repository runs under **native execution using staged pull requests from a fresh
`main`** (see `STATUS.md`). Practically:

- Branch from the latest `main`; never commit directly to `main`.
- Keep PRs small and single-purpose. Architecturally significant changes are gated
  by maintainer review (see `.github/CODEOWNERS`).
- The live source of truth for operating state is `reports/current_status.json`;
  the repo is currently `NON_PRODUCTION_DIAGNOSTIC` (paused pending source delivery).

## Quick start

```bash
python -m pip install -r requirements-dev.txt   # runtime + lint/type/test tooling
pre-commit install                              # optional but recommended
```

## Quality gates (all blocking in CI)

Run these locally before pushing — CI enforces every one:

| Gate | Command | CI workflow |
|------|---------|-------------|
| Lint | `ruff check .` | `lint.yml` |
| Format | `ruff format --check .` (`ruff format .` to fix) | `lint.yml` |
| Types | `python -m mypy` | `mypy.yml` |
| Tests | `pytest -q` | `ci.yml`, `tests.yml` (3.10–3.12) |
| Lockfile | `uv pip compile requirements.in --universal --python-version 3.10 -o requirements.lock` (no diff) | `lockfile.yml` |
| Docs sync | `python3 tools/check_docs_sync.py --base origin/main` | `docs-sync.yml` |

Notes:
- Pin parity matters: CI uses the versions in `requirements-dev.txt` (e.g. mypy
  `2.1.0`, ruff `0.15.18`). Use those locally so results match.
- `mypy` checks `moneysweep/` (scripts are followed but not yet reported).
- `ruff format` is the house style; a `.git-blame-ignore-revs` keeps blame readable
  across the one-time reformat.
- `docs-sync` fails its job on a violation, but a failing job blocks a merge only
  once `docs-sync` is a required status check on `main` (a repository setting).
  See *Documentation stays true* below.

### Documentation stays true

A document that describes this repo must not contradict it. If your change makes one
untrue, update that document in the same change. This is enforced: the `docs-sync` CI
job, the `docs-sync` pre-commit hook and a Claude Code Stop hook all run
`tools/check_docs_sync.py`, which checks three things.

1. **Co-change.** `.federation/docs-sync.json` declares which docs cover which paths.
   Changing a covered path without touching its doc fails, unless a commit message or
   the PR description carries `Docs-Impact: none - <reason>` (say why no doc needs to
   change; ten characters minimum, and reviewers will read it).
2. **References.** A change may not leave a doc pointing at a path that no longer
   exists. Only references *your change* broke count; older ones are not yours to fix
   here. A deliberate reference (a generated file, say) goes in `ignore_refs`, or is
   waived for that one doc with `Docs-Impact: <doc> - <reason>`.
3. **The manifest itself** must stay valid, and its globs must still match something.

Snapshots (dated audits, receipts, ADRs, changelogs) describe a moment rather than the
repo, so they are listed under `exempt_docs` and never forced to change. Setting
`"mode": "report"` in the manifest prints the same findings without failing the job;
use it only while triaging a new manifest. A failing job blocks a merge only once
`docs-sync` is a required status check for `main`, which is a repository setting.

`tools/check_docs_sync.py`, `.github/workflows/docs-sync.yml`, `.claude/settings.json`
and `CLAUDE.md` are rendered from templates in `thehub-pr` and must not be
hand-edited: change the template and re-render (`template-drift.yml` fails the
build if they diverge). `.federation/docs-sync.json` is this repo's own.

## Dependencies

Runtime deps are declared in `requirements.in` and compiled to `requirements.lock`
by [`uv`](https://github.com/astral-sh/uv). If you change a dependency, edit
`requirements.in` and regenerate the lock with the command above — the
`lockfile.yml` check fails on drift. Dependabot proposes weekly updates.

## Tests

- Use the markers in `pytest.ini`: `unit`, `integration`, `pipeline_gate`,
  `non_executing`, `external`.
- Reuse the shared fixtures in `tests/conftest.py` (`tmp_project`, `sample_*_csv`).
- Mock the network: adapters accept an injected `session=`, and credentials are read
  from env vars — never hit a live API in tests.

## Commit & PR

- Write clear, imperative commit messages explaining the *why*.
- Open the PR against `main` and fill out the template. Green CI is required.
- By contributing you agree your work is licensed under the repository's
  [MIT License](LICENSE).

See also `docs/BUILD_EXECUTION_SEQUENCE.md` for the active improvement roadmap and
`CODE_OF_CONDUCT.md` for community expectations.
