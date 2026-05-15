# Setup Guide

## Requirements

- Python 3.11 (pinned in CI via `.github/workflows/ci.yml`)
- Git
- No external services required for development — all CI seeds are committed

## Clone and Install

```bash
git clone https://github.com/jotaele44/contract-sweeper.git
cd contract-sweeper
python -m pip install -r requirements.txt
```

## Verify Installation

```bash
# Compile all modules (catches import errors and syntax issues)
python -m compileall contract_sweeper scripts tests

# Run tests
pytest -q
# Expected: 639 passed, 5 skipped

# Run validation gates
python -m contract_sweeper.runtime.validation_gates --root .
# Expected: {"passed": true, "failed_gate_count": 0}
```

If gates pass and tests pass, the environment is correctly set up.

## Environment Variables (optional)

Copy `.env.example` to `.env` if it exists, or create `.env` at repo root.
No API keys are required for core functionality — all registered sources
use unauthenticated public endpoints.

```bash
# .env — only needed if running live downloaders
# API keys referenced in source_registry.yaml under authentication: api_key:<VAR>
# Example:
# HIGHERGOV_API_KEY=...
```

**Never commit `.env`.** It is gitignored.

## Directory Structure

```
contract_sweeper/          # Python package
  runtime/                 # Production runtime (gates, signals, manifests)
  validation/              # Audit and coverage validation
  pipeline/                # R4 backfill orchestration (completed phase — archive candidate)
scripts/                   # Standalone scripts
  build_*.py               # Active build pipeline
  download_*.py            # Source downloaders (14 active + 62 expansion)
  ingest_*.py              # Local-file ingest (portal exports, manual drops)
  analyze_*.py             # Cross-reference analysis
  run_*.py                 # R4 phase runners (completed — archive candidates)
registries/                # Source + schema registries (YAML + generated JSON)
data/
  ci/seeds/                # Committed CI seed CSVs (satisfy gates without live data)
  staging/processed/       # Pipeline outputs (gitignored at top level; subdirs committed)
    execution/             # execution_chain_master.csv (committed)
    hud_drgr/              # HUD DRGR seed (committed)
    risk/                  # R7 risk signal outputs (committed)
  manifests/               # Per-source manifests + gate reports
  manual/                  # Drop zone for operator-supplied portal exports
tests/                     # pytest test suite
```

## Running the Pipeline

The canonical entry point chains the full pipeline in the correct order:

```bash
# Full pipeline: validate → build → signals → report
python scripts/pipeline.py all

# Individual steps
python scripts/pipeline.py validate   # run CI validation gates (exits 1 on failure)
python scripts/pipeline.py build      # build unified master + execution chains
python scripts/pipeline.py signals    # compute R7 risk signals
python scripts/pipeline.py report     # generate investigative report
python scripts/pipeline.py status     # print gate status, always exits 0
```

Each step can also be run directly:

```bash
# Build unified awards master (requires live USASpending data)
python scripts/build_unified_master.py

# Build risk signals from existing processed outputs
python scripts/build_risk_signals.py --root .

# Run validation gates (no network required)
python -m contract_sweeper.runtime.validation_gates --root .

# Run R7 risk signal gates
python -m contract_sweeper.runtime.risk_signal_gates --root .

# Generate report
python scripts/generate_report.py
```

## CI Pipeline

CI runs on every push and pull request:

```yaml
1. python -m compileall contract_sweeper scripts tests
2. pytest -q
3. python scripts/scan_for_secrets.py --root .
4. python -m contract_sweeper.runtime.validation_gates --root .
```

All four steps must pass (exit 0) for CI to succeed.
The gate step is **enforced** — `--allow-failed` has been removed.

## Adding a Manual Data Drop

For sources that require operator portal login (e.g., `hud_drgr_authorized`):

1. Download the export from the portal.
2. Place the file in `data/manual/{source_id}/`.
3. Run the corresponding ingest script: `python scripts/ingest_hud_drgr_exports.py`
4. The ingest script writes to `data/staging/processed/{source_id}/`.
5. Run `python -m contract_sweeper.runtime.validation_gates --root .` to confirm the gate passes.

See `data/staging/expansion/DOWNLOAD_INSTRUCTIONS.md` for per-source instructions.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Gate fails: `required_source_nonempty` | Run the relevant ingest/build script, or check `data/ci/seeds/` has the seed CSV |
| Gate fails: `manifest_present_per_required` | Run `python scripts/write_source_manifests.py` |
| `ModuleNotFoundError: contract_sweeper` | Run from repo root, or add root to `PYTHONPATH` |
| Tests fail after branch switch | Run `python -m compileall contract_sweeper` to catch stale `.pyc` files |
