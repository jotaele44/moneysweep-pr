# Materialization Runbook — Filling All Automatable Sources

This is the operator procedure to materialize every **automatable** source to
100% success. The target set and per-source path are defined by the readiness
classifier (`scripts/build_source_recovery_matrix.py`) and proved by the gate
test (`tests/test_materialization_readiness.py`).

> **Environment requirement:** this must run where outbound HTTPS is allowed.
> The default Claude-Code web sandbox blocks egress (HTTP 403), so no producer
> or adapter can fetch data there. Run this on a machine/CI with network access.

## Readiness snapshot (current)

See `reports/materialization_readiness.json`:

- **88** total registered sources
- **57 automatable** — all structurally `ready` (adapter or importable producer
  + declared outputs). This is the fill target.
- **5 automatable sources need an API key** at run time: `SAM_API_KEY`,
  `LDA_API_KEY`, `FEC_API_KEY`, `OPENCORPORATES_API_TOKEN`, `HIGHERGOV_API_KEY`.
- **31 queued / excluded** (not part of the automatable target):
  - `scraper_needed` (20) — PR-gov HTML/PDF surfaces; need a scraping adapter.
  - `manual_export` (6) — operator-supplied files (see step 3).
  - `semantic_duplicate` (3) — covered by a sibling source; never materialize alone.
  - `deferred_stub` (2) — NARA; intentionally unimplemented.

## Procedure

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Provide API keys
Copy `.env.example` to `.env` and fill the keys needed for full coverage
(template values shown — replace each with your real key in `.env`, never here):
```
SAM_API_KEY=paste_your_key_here            # required for sam_entities (entity adapter)
LDA_API_KEY=paste_your_key_here            # lobbying
FEC_API_KEY=paste_your_key_here            # campaign finance (DEMO_KEY works, capped)
OPENCORPORATES_API_TOKEN=paste_your_key_here
HIGHERGOV_API_KEY=paste_your_key_here
```
Adapter sources without a key will skip or run limited (non-fatal) — they remain
structurally ready, but won't reach 100% rows until the key is set.

### 3. (Optional) Drop manual-export files
Only needed to materialize the 6 queued `manual_export` sources. Per
`registries/manual_export_registry.yaml`, place files in each source's
`expected_drop_dir` (e.g. `data/manual/hud_drgr/`, `data/manual/act_transition/`,
`data/raw/OCE/`). These are **not** part of the automatable target; skip if you
only want the 57.

### 4. Confirm the gate before running
```bash
python3 run_all.py --only-setup --strict-preflight   # expect 0 structural errors
python3 -m pytest tests/test_materialization_readiness.py -q
```

### 5. Materialize
- **Adapter-backed sources** (35) — on-demand query path:
  ```bash
  python -m contract_sweeper.query --source <source_id> [--fy 2020,2021 ...]
  ```
- **Full pipeline** (producers + downstream) — registry-driven orchestrator:
  ```bash
  python3 run_all.py --strict-preflight
  ```
  Use the documented `--skip-*` flags to scope a run.

### 6. Regenerate reports and verify
```bash
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
```
Success criteria:
- `reports/materialization_readiness.json`: `automatable_ready == automatable_total`.
- `reports/gap_analysis_report.json`: every **automatable** source shows
  `fully_materialized` (note: overall `coverage_rate` is over *all 88* sources,
  so it will not reach 1.0 while the 31 queued sources remain unmaterialized —
  judge success against the automatable subset and `required_coverage_rate`).

## Definition of done (per source)

A source is `fully_materialized` (`scripts/gap_analysis_builder.py::_source_status`)
when **every** `expected_output` exists on disk, is non-empty, and — for CSVs —
has `row_count ≥ validation_threshold.min_rows`.

## Out of scope (separate, future work)

Building the 20 `scraper_needed` PR-gov adapters and integrating the manual
datasets (ACT/ACUDEN/PRASA/cabilderos/DCAA). Until then, those sources stay
queued and excluded from the automatable target by design.
