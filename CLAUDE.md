# CLAUDE.md — Contract-Sweeper Session Context

## What This Repo Is

Governed analytical pipeline for Puerto Rico federal contracting, disaster-recovery
spending, and political-finance data. 14 registered sources, R5 CI-enforced gates,
R7 deterministic risk signals.

## Current Branch

`claude/r7-risk-signal-engine` (active development branch)

Push target per session instructions: `claude/assess-branch-status-zPGba`

## Key Commands

```bash
pytest -q                                                       # run all tests
pytest -m unit -q                                               # fast unit tests only
python scripts/pipeline.py all                                  # full pipeline
python scripts/pipeline.py status                               # gate status (always exits 0)
python -m contract_sweeper.runtime.validation_gates --root .    # R5 gates directly
python scripts/check_import_graph.py --root .                   # import graph check
python -m compileall contract_sweeper scripts tests             # compile check
python scripts/scan_for_secrets.py --root .                     # secret scan
```

## Architecture

```
Sources → Normalisation → Validation (R5) → Signal (R7) → Output
           pipeline/         runtime/         runtime/      output/
```

- `contract_sweeper/pipeline/` — R4-era pipeline layer (import-graph isolated; archive target)
- `contract_sweeper/runtime/` — Active layer: validation_gates, risk_signals, risk_signal_gates
- `contract_sweeper/validation/` — Source validators and production status
- `scripts/pipeline.py` — Canonical orchestration entry point
- `registries/source_registry.yaml` — 14-source registry (source of truth for CI gates)

## Test Markers

```
unit             Pure logic tests, minimal filesystem coupling
integration      Multi-module or filesystem-backed tests
pipeline_gate    Gate-enforcement invariant tests
non_executing    Audits, docs, config, status checks
external         External source boundary tests
slow             Long-running tests (excluded from default run)
```

## What NOT To Do

- Never commit `.env`, `*.key`, or any credential file
- Never use `--allow-failed` with validation_gates (CI blocks it; no exceptions)
- Never `import contract_sweeper.pipeline` in new active code (CI enforces 0 violations)
- Never push directly to `main` — all work goes through PRs
- Never add a source without updating `registries/source_registry.yaml`
- Never archive/delete modules without updating `module_inventory.csv`
- Never skip hooks (`--no-verify`, `--no-gpg-sign`) unless explicitly requested
- Never force-push to `main`

## Critical Files

| File | Role |
|---|---|
| `registries/source_registry.yaml` | 14-source registry — gate reads this |
| `contract_sweeper/runtime/risk_signals.py` | R7 signal engine (8 families, SCHEMA_VERSION="r7_v1") |
| `contract_sweeper/runtime/validation_gates.py` | R5 gate enforcer (SOURCE_COVERAGE_TARGET=0.93) |
| `contract_sweeper/runtime/risk_signal_gates.py` | R7 gate module (5 gates) |
| `scripts/pipeline.py` | Canonical entry point |
| `scripts/check_import_graph.py` | Import graph checker (KNOWN_EXCEPTIONS for 1 CI-wired wrapper) |
| `data/ci/seeds/` | Committed CI seed data (gate-satisfying, last in expected_outputs list) |
| `data/manifests/` | Generated gate reports (gitignored except seeds) |
| `archive/` | Inert archived code — not collected by pytest (testpaths=tests in pytest.ini) |

## Gitignore Notes

- `data/staging/processed/*.csv` — gitignored at top level
- `data/staging/processed/execution/`, `hud_drgr/`, `risk/` — subdirectories are committable
- `data/staging/processed/enrichment/` — always gitignored (may contain vendor PII)
- `.env` — gitignored; API keys live here only

## Module Inventory

304 total modules · 47.9% identified as archiveable (see `module_inventory.csv`)

Categories: KEEP (167) · ARCHIVE (118) · MERGE (18) · DELETE (1)

Future archival targets (do not execute without explicit instruction):
1. PR-C: Merge analyze_fec_crossref + analyze_lobbying_crossref → analyze_political_crossref.py
2. PR-D: Archive 62 expansion download scripts → archive/download_expansion/
3. PR-E: Archive contract_sweeper/pipeline/ → archive/pipeline_r4/ (gate: import graph CI green ≥1 run)
