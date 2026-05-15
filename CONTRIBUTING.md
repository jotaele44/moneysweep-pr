# Contributing to Contract-Sweeper

## Setup

See [SETUP.md](SETUP.md) for full environment setup, API key handling, and
the manual data-drop workflow for sources that cannot be auto-downloaded.

## Development Workflow

```bash
# 1. Branch from the active development branch
git checkout claude/r7-risk-signal-engine
git checkout -b your-feature-branch

# 2. Make changes, write tests
pytest -m unit -q   # fast feedback loop

# 3. Verify gates before pushing
python scripts/pipeline.py status
python scripts/check_import_graph.py --root .
python -m compileall contract_sweeper scripts tests

# 4. Full test run
pytest -q

# 5. Push and open PR targeting main
git push -u origin your-feature-branch
```

## Adding a New Data Source

1. Add an entry to `registries/source_registry.yaml` with `required: true` if the
   source is part of the 14-gate baseline, or `required: false` for supplemental.
2. Write a downloader in `scripts/download_<source>.py`.
3. Add or extend a normaliser — new sources go in `contract_sweeper/runtime/`,
   not `contract_sweeper/pipeline/` (the pipeline layer is import-graph isolated).
4. Add or extend a gate entry in `contract_sweeper/runtime/validation_gates.py`.
5. Commit a CI seed file to `data/ci/seeds/<source>_seed.csv` with ≥1 data row.
6. Verify: `python -m contract_sweeper.runtime.validation_gates --root .`

The gate uses OR semantics on `expected_outputs`: any file in the list having ≥1 data
row satisfies the gate. The CI seed is listed last so live data takes precedence.

## Adding a Risk Signal

1. Add a signal family function to `contract_sweeper/runtime/risk_signals.py`.
   Follow the existing pattern: return a `pd.DataFrame` with columns matching
   `SIGNAL_COLUMNS`. Set a deterministic `signal_id` and always populate `explanation`.
2. Register the function in the `SIGNAL_FAMILIES` list at the bottom of that file.
3. Add unit tests in `tests/test_risk_signals.py` covering the happy path and the
   threshold boundary (e.g., N-1 awards → no signal, N awards → signal fires).
4. If the signal requires a new gate, add it to `contract_sweeper/runtime/risk_signal_gates.py`
   following the `gate_*` naming convention and register it in `run_all_gates()`.

## Archival Rules

The import graph is CI-enforced: no active code outside `contract_sweeper/pipeline/`
may import from that layer.

Before archiving anything:
```bash
python scripts/check_import_graph.py --root .   # must show PASS: 0 unexpected imports
```

Archival procedure:
1. `git mv <files> archive/<subdirectory>/`
2. Update `module_inventory.csv` — set `category` to `ARCHIVED`.
3. Run `pytest -q` — all tests must still pass (pytest only collects from `tests/`).
4. Run `python -m compileall contract_sweeper scripts tests` — no errors.

Never delete committed files outright. The `archive/` directory preserves full
git history without polluting the active module tree.

## Security

- **No API keys in code or commits.** Keys go in `.env` (gitignored) only.
- **No PII data committed.** `data/staging/processed/enrichment/` is gitignored.
- Run `python scripts/scan_for_secrets.py --root .` before each commit.
- Do not use `--no-verify` to bypass pre-commit hooks.

## CI Requirements

Every PR must pass:

| Check | Command |
|---|---|
| Compile | `python -m compileall contract_sweeper scripts tests` |
| Tests | `pytest -q` |
| Secret scan | `python scripts/scan_for_secrets.py --root .` |
| R5 gate | `python -m contract_sweeper.runtime.validation_gates --root .` |
| Import graph | `python scripts/check_import_graph.py --root .` |

All checks run automatically in `.github/workflows/ci.yml`. There is no manual bypass.

## Commit Message Style

```
<short imperative summary> (<≤70 chars)

Optional body explaining why, not what.
```

Examples from this repo's history:
- `Phase 7: deterministic risk signal engine (R7 v1)`
- `PR-2/3/4: canonical entry point, wrapper archival, import graph proof`
- `CI gate enforcement: remove --allow-failed, add committed CI seeds`
