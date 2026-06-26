# Setup Guide — moneysweep-pr

**Tested on:** Python 3.9+ · Ubuntu/Debian · macOS  
**Estimated setup time:** 5 minutes (no data download required for tests)

> Use **Python 3.11** locally (see `.python-version`) to match CI — newer interpreters (3.14+) can produce false test failures in R4.8 backfill tests due to dict-ordering changes.

---

## 1. Clone

```bash
git clone https://github.com/jotaele44/moneysweep-pr.git
cd moneysweep-pr
```

No special credentials are needed to clone — the repository is public.

---

## 2. Install Dependencies

```bash
pip install -r requirements.txt
```

Core dependencies (all available via pip, no compiled extensions required):

| Package | Version | Purpose |
|---------|---------|---------|
| pandas | ≥2.0.0 | DataFrame processing |
| requests | ≥2.28.0 | HTTP downloads |
| lxml | ≥4.9.0 | XML/HTML parsing |
| pytest | ≥7.0.0 | Test runner |
| rapidfuzz | ≥3.0.0 | Fuzzy entity matching |
| python-dotenv | ≥1.0.0 | `.env` loading |
| pyarrow | ≥14.0.0 | Parquet I/O |
| PyYAML | ≥6.0 | Registry files |
| networkx | ≥3.0 | Graph analysis |

---

## 3. Configure API Keys (Optional for Tests)

```bash
cp .env.example .env
# Edit .env and fill in your keys
```

Tests do **not** require real API keys. Keys are only needed to run live data downloads.  
See `.env.example` for which keys are required vs. optional.  
See `docs/SECRET_HANDLING_POLICY.md` for key storage rules.

---

## 4. Run Tests

```bash
python3 -m pytest tests/ -q
```

Expected output on a clean clone:
```
594 passed, 4 skipped in ~10s
```

The 4 skipped tests require live network access or large data files.  
All 594 passing tests run fully offline with no API keys required.

---

## 5. Directory Structure for Data (Optional)

The `data/` directory is gitignored but its structure is tracked via `.gitkeep` files. To initialize:

```bash
python3 scripts/setup_directories.py
```

This creates all required subdirectories without downloading any data.

---

## 6. Verify Configuration

```bash
python3 -c "from scripts.config import *; print('Config OK')"
```

---

## 7. Run the Full Pipeline (Requires Source Data)

The production pipeline is currently **paused** pending delivery of 21 missing source files.  
See `STATUS.md` and `reports/gap_analysis_report.csv` before running.

```bash
# Do NOT run this until sources are delivered and unfreeze conditions are met:
python3 run_all.py
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `ModuleNotFoundError: No module named 'scripts'` | Run from the repo root, not a subdirectory |
| `ImportError: No module named 'pandas'` | Run `pip install -r requirements.txt` |
| Tests fail with `FileNotFoundError` | Run `python3 scripts/setup_directories.py` first |
| API key errors during downloads | Copy `.env.example` to `.env` and fill in keys |

---

## Key Entry Points

| Script | Purpose |
|--------|---------|
| `run_all.py` | Full pipeline orchestrator |
| `scripts/config.py` | Central configuration (read first) |
| `scripts/build_unified_master.py` | Core ETL — builds the awards master |
| `scripts/auto_download.py` | Automated bulk downloader |
| `scripts/generate_report.py` | Report generation |
| `scripts/run_production_status_gate.py` | Check current production readiness |
