# Contributing to Contract-Sweeper

Thanks for helping improve Contract-Sweeper — a pipeline for tracing Puerto Rico
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

Notes:
- Pin parity matters: CI uses the versions in `requirements-dev.txt` (e.g. mypy
  `1.11.2`). Use those locally so results match.
- `mypy` checks `contract_sweeper/` (scripts are followed but not yet reported).
- `ruff format` is the house style; a `.git-blame-ignore-revs` keeps blame readable
  across the one-time reformat.

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
