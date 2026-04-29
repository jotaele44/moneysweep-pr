# Contract-Sweeper

![Tests](https://github.com/jotaele44/contract-sweeper/actions/workflows/tests.yml/badge.svg)

Puerto Rico Federal Contracts Data Pipeline — automated acquisition, validation,
normalization, and coverage analysis of federal procurement data (FY 2000–2025).

## Overview

Contract-Sweeper gathers federal contract data related to Puerto Rico from three
sources (FPDS, USASpending, FSRS), validates the downloads, normalizes them into
a standard schema, and checks for complete fiscal-year coverage across a 26-year
window. The pipeline handles 13 distinct datasets spanning 8 FPDS time-window
files, 4 USASpending query files, and 1 FSRS subcontract file.

## Architecture

```
Step 1    Setup Directories          scripts/setup_directories.py
Step 2    Generate Instructions      scripts/download_instructions.py
Step 3    Auto-Download Datasets     scripts/auto_download.py
Step 4    Validate Downloads         scripts/validate_downloads.py
Step 5    Normalize & Transform      scripts/normalize_expansion_inputs.py
Step 5.5  Cross-File Dedup + Master  scripts/deduplicate_master.py
Step 6    Validate Coverage          scripts/validate_expansion_coverage.py
Step 7    SAM.gov UEI Enrichment     scripts/sam_enrichment.py  (optional)
```

All steps are orchestrated by `run_all.py`, which produces a summary report
with timing, coverage stats, and pass/fail status for each stage.

## Data Sources

| # | Filename | Source | Years | Description |
|---|----------|--------|-------|-------------|
| 1 | `expansion_fpds_2000_2004_direct.csv` | FPDS | 2000–2004 | Place of Performance = PR |
| 2 | `expansion_fpds_2000_2004_vendor.csv` | FPDS | 2000–2004 | Vendor State = PR |
| 3 | `expansion_fpds_2005_2008_direct.csv` | FPDS | 2005–2008 | PoP = PR (**must contain 2007**) |
| 4 | `expansion_fpds_2005_2008_vendor.csv` | FPDS | 2005–2008 | Vendor = PR (**must contain 2007**) |
| 5 | `expansion_fpds_2009_2016_direct.csv` | FPDS | 2009–2016 | PoP = PR |
| 6 | `expansion_fpds_2009_2016_vendor.csv` | FPDS | 2009–2016 | Vendor = PR |
| 7 | `expansion_fpds_2017_2025_direct.csv` | FPDS | 2017–2025 | PoP = PR |
| 8 | `expansion_fpds_2017_2025_vendor.csv` | FPDS | 2017–2025 | Vendor = PR |
| 9 | `expansion_idv_indirect_pr.csv` | USASpending | 2000–2025 | IDV awards referencing PR (non-PR recipients) |
| 10 | `expansion_dod_upr_2001_2015.csv` | USASpending | 2001–2015 | DoD corridor (UPR, military bases) |
| 11 | `expansion_dod_upr_2016_2025.csv` | USASpending | 2016–2025 | DoD corridor (post-2016) |
| 12 | `expansion_reconstruction_2017_2025.csv` | USASpending | 2017–2025 | Post-hurricane reconstruction (FEMA/HUD/DOT/USACE/VA) |
| 13 | `expansion_subcontracts_pr.csv` | FSRS | 2000–2025 | Subcontract data, PoP = PR |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the full pipeline
python3 run_all.py

# Or run only setup (directories + download instructions)
python3 run_all.py --only-setup
```

After Step 2, detailed per-file download instructions are available at
`data/staging/expansion/DOWNLOAD_INSTRUCTIONS.md`.

## CLI Reference

### run_all.py (orchestrator)

```
python3 run_all.py [flags]

--only-setup        Run steps 1-2 only (dirs + instructions)
--skip-download     Skip step 3 (auto-download)
--manual-only       Alias for --skip-download
--force-download    Re-download even if files already exist
--skip-validation   Skip step 4 (download validation)
--skip-normalize    Skip step 5 (normalization)
--skip-dedup        Skip step 5.5 (cross-file dedup + master build)
--skip-coverage     Skip step 6 (coverage validation)
--skip-enrichment   Skip step 7 (SAM.gov UEI enrichment)
```

### Individual scripts

```bash
python3 scripts/auto_download.py                  # download all
python3 scripts/auto_download.py --force           # re-download existing
python3 scripts/auto_download.py --only=fpds       # FPDS only
python3 scripts/auto_download.py --only=usaspending
python3 scripts/validate_downloads.py              # validate downloads
python3 scripts/normalize_expansion_inputs.py      # normalize all
python3 scripts/validate_expansion_coverage.py     # check year coverage
```

## Directory Structure

```
Contract-Sweeper/
├── run_all.py                      # 6-step pipeline orchestrator
├── requirements.txt                # pandas, requests, lxml
├── README.md
├── scripts/
│   ├── config.py                   # paths, manifest, column families, helpers
│   ├── setup_directories.py        # step 1: create directory structure
│   ├── download_instructions.py    # step 2: generate DOWNLOAD_INSTRUCTIONS.md
│   ├── auto_download.py            # step 3: FPDS/USASpending/FSRS downloads
│   ├── validate_downloads.py       # step 4: file existence + column checks
│   ├── normalize_expansion_inputs.py  # step 5: standardize schema + dates
│   └── validate_expansion_coverage.py # step 6: FY 2000-2025 coverage matrix
├── tests/                          # pytest test suite
│   ├── conftest.py                 # shared fixtures
│   ├── test_config.py
│   ├── test_normalize.py
│   ├── test_validate_downloads.py
│   ├── test_validate_coverage.py
│   ├── test_setup_directories.py
│   └── test_download_instructions.py
└── data/
    ├── staging/
    │   ├── expansion/              # raw downloaded CSVs (13 files)
    │   └── processed/              # normalized CSVs
    ├── raw/                        # reserved
    └── logs/                       # timestamped pipeline logs
```

## Pipeline Steps

### Step 1: Setup Directories
Creates the full `data/` directory tree and `.gitkeep` files for version control.

### Step 2: Generate Download Instructions
Produces `DOWNLOAD_INSTRUCTIONS.md` with per-file step-by-step browser instructions
and a machine-readable `manifest.json` for all 13 datasets.

### Step 3: Auto-Download
Downloads 12 of 13 datasets automatically:
- **FPDS** (8 files): Atom/XML feed at `fpds.gov`, 500 rows per page, with retry logic.
- **USASpending** (4 files): REST API at `api.usaspending.gov`, 100 results per page.
- **FSRS** (1 file): Attempts automated form POST; falls back to manual instructions.

### Step 4: Validate Downloads
Checks each file for: existence, non-empty rows, required column families
(date, vendor, agency, amount), and data quality (non-null key fields).

### Step 5: Normalize & Transform
Standardizes column names across all sources to `STANDARD_COLUMNS`, parses dates
(flexible format), derives federal fiscal year (Oct–Sept boundary), cleans
dollar amounts, deduplicates within each file, and outputs to `data/staging/processed/`.

### Step 5.5: Cross-File Deduplication + Master Build
Merges all 13 normalized CSVs into a single `pr_contracts_master.csv`. Removes
duplicate contracts that appear in both `*_direct` and `*_vendor` files using a
composite key of `(contract_id, award_date, vendor_name, obligated_amount)`.
Source-file provenance is consolidated into a comma-joined `source_file` column.

### Step 6: Validate Coverage
Builds a fiscal-year coverage matrix (2000–2025), checks for the **critical 2007 gap**
in FPDS 2005–2008 files (FPDS migrated platforms around 2007), and verifies
timeline continuity with no internal gaps.

### Step 7: SAM.gov UEI Enrichment (optional)
Resolves vendor UEI/CAGE/DUNS via the SAM.gov Entity Information API v2, with
USASpending.gov as a fallback. Requires a free API key — see setup below.

**Setup:**
```bash
# Option A — environment variable
export SAM_API_KEY=your_key_here

# Option B — .env file (gitignored, never committed)
cp .env.example .env
# edit .env and replace placeholder with real key
```

**Running:**
```bash
python3 run_all.py                              # includes enrichment if key is set
python3 run_all.py --skip-enrichment           # skip enrichment
python3 scripts/sam_enrichment.py --dry-run    # validate config, no API calls
python3 scripts/sam_enrichment.py --resume     # resume from checkpoint
python3 scripts/sam_enrichment.py --top 500    # top 500 vendors by value only
```

**Outputs** (in `data/staging/processed/enrichment/`):
- `vendor_uei_index.csv` — resolved UEI/CAGE/DUNS per vendor
- `master_enriched.csv` — master CSV with UEI columns filled
- `enrichment_summary.json` — coverage stats and gate result
- `failed_lookups.csv` — vendors needing manual resolution

⚠️ The enrichment output directory is gitignored — it may contain vendor PII.

## Known Issues

- **2007 FPDS gap**: FPDS migrated platforms circa 2007. The FY2005–2008 files may
  have spotty 2007 data. The pipeline detects this and raises a critical alert.
  If 2007 is missing, download it separately with date range 10/01/2006–09/30/2007.

- **FSRS manual download**: FSRS has no public API. The auto-download attempts a
  form POST but typically requires a browser session. Follow the manual instructions
  in `DOWNLOAD_INSTRUCTIONS.md`.

- **FPDS 500K row limit**: FPDS exports may cap at 500,000 rows. If a time window
  hits this limit, split into smaller date ranges and combine the CSVs.

## Testing

```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests
python3 -m pytest tests/ -v

# Run a specific test file
python3 -m pytest tests/test_config.py -v

# Run with coverage (requires pytest-cov)
python3 -m pytest tests/ --cov=scripts --cov-report=term-missing
```

## Celestial Anomaly Detector (New)

For high-volume astrophotography review, use:

```bash
python3 scripts/celestial_anomaly_detector.py /path/to/media \
  --output data/staging/processed/celestial_anomalies \
  --frame-step 3 --threshold 2.8 --top 1000
```

What it does:
- Scans images and videos (`.png`, `.jpg`, `.tif`, `.mp4`, `.mov`, `.mkv`, etc.).
- Extracts per-frame metrics (brightness shifts, motion, edge-density, hot-pixel ratio).
- Computes robust z-scores and a composite anomaly score.
- Exports ranked results to `anomalies.csv` and `anomalies.json`.
