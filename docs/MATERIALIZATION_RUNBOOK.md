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

- **85** total registered sources
- **55 automatable** — all structurally `ready` (adapter or importable producer
  + declared outputs). This is the fill target.
- **5 automatable sources need an API key** at run time: `FEC_API_KEY`,
  `FINANCIALDATA_API_KEY`, `HIGHERGOV_API_KEY`, `OPENCORPORATES_API_TOKEN`,
  `SAM_API_KEY`.
- **30 queued / excluded** (not part of the automatable target):
  - `scraper_needed` (15) — PR-gov HTML/PDF surfaces; need a scraping adapter.
  - `manual_export` (10) — operator-supplied files (see step 3).
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
```bash
FEC_API_KEY=paste_your_key_here            # campaign finance (DEMO_KEY works, capped)
FINANCIALDATA_API_KEY=paste_your_key_here  # optional commercial enrichment
HIGHERGOV_API_KEY=paste_your_key_here      # HigherGov supplemental contract data
OPENCORPORATES_API_TOKEN=paste_your_key_here
SAM_API_KEY=paste_your_key_here            # sam_entities entity adapter
```
Adapter sources without a key will skip or run limited (non-fatal) — they remain
structurally ready, but won't reach 100% rows until the key is set.

### 3. (Optional) Drop manual-export files
Only needed to materialize the 10 queued `manual_export` sources. Per
`registries/manual_export_registry.yaml`, place files in each source's
`expected_drop_dir` (for example `data/manual/hud_drgr/`,
`data/manual/act_transition/`). These are **not** part of the automatable target;
skip if you only want the 55.

### 4. Confirm the gate before running
```bash
python3 run_all.py --only-setup --strict-preflight   # expect 0 structural errors
python3 -m pytest tests/test_materialization_readiness.py -q
```

### 5. Materialize
- **Adapter-backed sources** (42) — on-demand query path:
  ```bash
  python -m contract_sweeper.query --source <source_id> [--fy 2020,2021 ...]
  ```
- **Producer-backed sources** (13) — registry-driven producer/orchestrator path:
  ```bash
  python3 run_all.py --strict-preflight
  ```
  Use the documented `--skip-*` flags to scope a run.

### 6. Build the financial-flow export bridge
After upstream financial masters are present, regenerate the canonical flow
master. This writes both the normalized parquet and the processed CSV bridge that
the federation exporter consumes:
```bash
python3 scripts/build_financial_flows_master.py --force
```
Expected outputs:
- `data/normalized/financial_flows_master.parquet`
- `data/staging/processed/financial_flows_master.csv`

The CSV bridge includes `flow_date`, derived in precedence order from
`flow_date`, `drawdown_date`, `obligation_date`, then `award_date`.

### 7. Regenerate reports and verify
```bash
python3 scripts/gap_analysis_builder.py
python3 scripts/build_source_recovery_matrix.py
```
Success criteria:
- `reports/materialization_readiness.json`: `automatable_ready == automatable_total`.
- `reports/gap_analysis_report.json`: every **automatable** source shows
  `fully_materialized` (note: overall `coverage_rate` is over *all 85* sources,
  so it will not reach 1.0 while the 30 queued sources remain unmaterialized —
  judge success against the automatable subset and `required_coverage_rate`).

## Definition of done (per source)

A source is `fully_materialized` (`scripts/gap_analysis_builder.py::_source_status`)
when **every** `expected_output` exists on disk, is non-empty, and — for CSVs —
has `row_count ≥ validation_threshold.min_rows`.

## Out of scope (separate, future work)

Building the 15 `scraper_needed` PR-gov adapters and integrating the 10 manual
export datasets. Until then, those sources stay queued and excluded from the
automatable target by design.
