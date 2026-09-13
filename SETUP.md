# Setup Guide — moneysweep-pr

**Local federation baseline:** Python 3.11  
**Supported systems:** macOS and Ubuntu/Debian

MoneySweep is one producer in the PRII federation. It installs and runs from an isolated clone — no `thehub-pr` sibling checkout is required; the shared `prii-*` packages resolve via a pinned `git+https` reference in `requirements.txt` (see ADR 0007 in `thehub-pr`).

## Python policy

The following surfaces must remain aligned:

- `.python-version`: `3.11`
- `pyproject.toml` mypy target: `3.11`
- `pyproject.toml` Ruff target: `py311`
- `Makefile` lock compiler baseline: `3.11`
- `requirements.lock` generation provenance: `--python-version 3.11`

Only the workflows that are meant to mirror this exact local baseline are pinned
to `3.11`: `ci.yml`, `lint.yml`, `mypy.yml`, `lockfile.yml`. `make check` (below)
reproduces these locally, so a clean `make check` on `.venv` is a faithful
preview of them. The rest of the gating CI surface — `tests.yml`,
`pre-commit.yml`, `production-status-gate.yml`, and most automation/source
workflows — currently runs on `3.13` (`template-drift.yml` and
`gui-capability-parity.yml` run on `3.12`); nothing enforces that these track
`3.11`, and there is no committed rationale for the split. Contributors should
not assume a green `make check` implies these other workflows will also pass —
verify against actual CI on the PR.

Do not use one virtual environment for the entire federation. Every repository owns a private `.venv`.

## 1. Clone the repository

```bash
git clone https://github.com/jotaele44/moneysweep-pr.git
cd moneysweep-pr
```

No sibling checkout is required. `moneysweep-pr` resolves the shared
`prii-maintenance` package via a pinned `git+https` dependency declared in
`requirements.txt` — installing it fetches that commit directly, regardless
of where this clone lives on disk.

## 2. Create the private environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
```

The interpreter should report Python 3.11:

```bash
python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")'
```

Local setup must not use `pip` or `uv pip install --system` outside `.venv`.

## 3. Select a dependency profile

The files have distinct ownership:

| Profile | Files | Purpose |
|---|---|---|
| Certified-core runtime candidate | `requirements.in`, `requirements.txt`, `requirements.lock` | Pipeline, parsers, local storage, exports, and Hub runtime execution |
| Audit/development | `requirements-dev.txt` | Runtime closure plus lint, typing, pytest, coverage, and type stubs |

`requirements.in` and `requirements.txt` must remain byte-identical. The
runtime lock must not contain pytest or pytest-cov. The development manifest
includes runtime through `-r requirements.txt`; it does not duplicate the
runtime list.

For the exact runtime environment:

```bash
python -m pip install -r requirements.lock
```

For development, audit, and tests:

```bash
python -m pip install -r requirements-dev.txt
```

Validate profile boundaries before installation:

```bash
python3 scripts/validate_dependency_planes.py
# or
make dependency-plane
```

The validator also checks `federation.json`: `setup` prepares the full audit/test
environment, while `runtime_setup` installs only the runtime manifest. This
preserves the existing Hub test contract without making test tooling part of
the certified-core runtime profile.

The Makefile assumes `.venv` is active and routes installs through `python -m pip`.

## 4. Configure optional credentials

```bash
cp .env.example .env
```

Tests do not require real API keys. Credentials are needed only for explicitly authorized live data acquisition. Follow `docs/SECRET_HANDLING_POLICY.md`; never commit `.env` or key material.

Instead of hand-editing `.env`, `scripts/set_api_key.py` can set individual keys:

```bash
python3 scripts/set_api_key.py --list        # show which keys are set/missing
python3 scripts/set_api_key.py SAM_API_KEY    # prompts for the value (hidden input)
```

The diagnostic dashboard's "API Keys" tab (see `dashboard/README.md`) offers the same thing from the browser.

## 5. Run the local quality bar

```bash
make check
```

Equivalent commands:

```bash
python3 scripts/validate_dependency_planes.py
python -m compileall moneysweep scripts tests
python -m pytest
python -m mypy
ruff check .
ruff format --check .
```

## 6. Verify lockfile provenance

The runtime lock is generated with the same Python baseline as the workspace:

```bash
make lock-check
```

To regenerate deliberately:

```bash
make lock
```

The lockfile drift workflow recompiles with Python 3.11, reruns the dependency
profile validator, and fails when the committed output differs. Do not edit the
lockfile manually. The audit/development manifest remains separately pinned for
the principal quality tools; a complete retained-byte development lock is still
required before `OFFLINE_REPRODUCIBLE_BUILD` can pass.

## 7. Initialize optional data directories

```bash
python scripts/setup_directories.py
```

This creates required local directories without downloading data.

## 8. Manual-source drops

Operator-supplied sources are documented in `docs/MANUAL_SOURCE_OPERATIONS.md`. Preserve the source-freshness, receipt, provenance, and no-raw-upload controls.

## 9. Production pipeline boundary

Before running the full pipeline, inspect `STATUS.md`, the production-status gate, and the current source-gap report.

```bash
python scripts/run_production_status_gate.py
```

Do not run `python run_all.py` unless the repository’s explicit unfreeze and source-readiness conditions are satisfied. A valid local environment does not authorize production execution.

## 10. Diagnostic dashboard

The dashboard is a diagnostic surface. The supported federation product surface is TheHub.

Development mode:

```bash
uvicorn server.backend.main:app --reload --port 8000
```

In another process:

```bash
cd dashboard
npm ci --no-audit --no-fund
npm run dev
```

Desktop and packaged-app procedures are governed separately by the shared `prii_desktop` runtime and its coordinated PR sequence.

## Troubleshooting

| Problem | Resolution |
|---|---|
| Python is not 3.11 | Recreate `.venv` with `python3.11 -m venv .venv` |
| Shared package cannot resolve | Confirm network access to GitHub — the `prii-maintenance` dependency is fetched from a pinned `git+https` URL on install, not a local path |
| `pip` writes outside the repository | Deactivate the global environment, activate `.venv`, and use `python -m pip` |
| Dependency profile validation fails | Restore runtime/dev ownership before installing or regenerating locks |
| Lockfile drift fails | Run `make lock` under Python 3.11 and review the complete diff |
| Tests need absent local directories | Run `python scripts/setup_directories.py` |
| Live-source command requests credentials | Stop unless the specific live execution has been authorized |

## Key entry points

| Path | Purpose |
|---|---|
| `run_all.py` | Full pipeline orchestrator; production-gated |
| `scripts/config.py` | Central configuration |
| `scripts/build_unified_master.py` | Core ETL |
| `scripts/run_production_status_gate.py` | Production-readiness check |
| `scripts/validate_dependency_planes.py` | Runtime/dev/Hub profile gate |
| `federation.json` | Producer commands and readiness declaration |
| `Makefile` | Local quality and lockfile commands |
