"""
Shared configuration for the Puerto Rico Federal Contracts Data Pipeline.
Single source of truth for paths, file manifest, column families, and helpers.
"""

import logging
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data"
STAGING_DIR = DATA_DIR / "staging"
EXPANSION_DIR = STAGING_DIR / "expansion"
PROCESSED_DIR = STAGING_DIR / "processed"
RAW_DIR = DATA_DIR / "raw"
LOGS_DIR = DATA_DIR / "logs"

# Consolidated master and enrichment outputs
MASTER_PATH = PROCESSED_DIR / "pr_contracts_master.csv"
ENRICHMENT_OUTPUT_DIR = PROCESSED_DIR / "enrichment"

# ---------------------------------------------------------------------------
# Expanded dataset directories (raw + processed masters)
# ---------------------------------------------------------------------------

RAW_GRANTS_DIR = DATA_DIR / "raw" / "grants"
RAW_SUBAWARDS_DIR = DATA_DIR / "raw" / "subawards"
RAW_FEMA_PA_DIR = DATA_DIR / "raw" / "fema_pa"
RAW_FEMA_HMGP_DIR = DATA_DIR / "raw" / "fema_hmgp"
RAW_RESEARCH_DIR = DATA_DIR / "raw" / "research"
RAW_SBA_DIR = DATA_DIR / "raw" / "sba"
RAW_SLFRF_DIR = DATA_DIR / "raw" / "slfrf"
RAW_CDBG_DR_DIR = DATA_DIR / "raw" / "cdbg_dr"

EXPANDED_RAW_DIRS = [
    RAW_GRANTS_DIR, RAW_SUBAWARDS_DIR, RAW_FEMA_PA_DIR,
    RAW_FEMA_HMGP_DIR, RAW_RESEARCH_DIR, RAW_SBA_DIR,
    RAW_SLFRF_DIR, RAW_CDBG_DR_DIR,
]

# Dataset master paths
GRANTS_MASTER_PATH = PROCESSED_DIR / "pr_grants_master.csv"
SUBAWARDS_MASTER_PATH = PROCESSED_DIR / "pr_subawards_master.csv"
FEMA_PA_MASTER_PATH = PROCESSED_DIR / "pr_fema_pa_master.csv"
FEMA_HMGP_MASTER_PATH = PROCESSED_DIR / "pr_fema_hmgp_master.csv"
RESEARCH_MASTER_PATH = PROCESSED_DIR / "pr_research_master.csv"
SBA_MASTER_PATH = PROCESSED_DIR / "pr_sba_loans_master.csv"
SLFRF_MASTER_PATH = PROCESSED_DIR / "pr_slfrf_master.csv"
CDBG_DR_MASTER_PATH = PROCESSED_DIR / "pr_cdbg_dr_master.csv"
UNIFIED_MASTER_PATH = PROCESSED_DIR / "pr_all_awards_master.csv"

ALL_DATASET_MASTERS = [
    GRANTS_MASTER_PATH, SUBAWARDS_MASTER_PATH, FEMA_PA_MASTER_PATH,
    FEMA_HMGP_MASTER_PATH, RESEARCH_MASTER_PATH, SBA_MASTER_PATH,
    SLFRF_MASTER_PATH, CDBG_DR_MASTER_PATH,
]

CANONICAL_COLUMNS = [
    "award_id", "recipient_name", "recipient_uei", "awarding_agency",
    "awarding_sub_agency", "obligated_amount", "award_date", "fiscal_year",
    "pop_state", "pop_county", "description", "source_file",
    "source_dataset", "award_category",
]

ALL_DIRS = [DATA_DIR, STAGING_DIR, EXPANSION_DIR, PROCESSED_DIR, RAW_DIR, LOGS_DIR] + EXPANDED_RAW_DIRS

# ---------------------------------------------------------------------------
# Download manifest — the 13 expected expansion files
# ---------------------------------------------------------------------------

DOWNLOAD_MANIFEST = [
    # ---- FPDS: 4 time windows x 2 filter types = 8 files ----
    {
        "filename": "expansion_fpds_2000_2004_direct.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2000,
        "year_end": 2004,
        "filter_type": "direct",
        "filters": {
            "Place of Performance State": "PR",
            "Date Signed": "10/01/2000 to 09/30/2004",
        },
        "description": "FPDS contracts performed in Puerto Rico, FY2000-2004",
    },
    {
        "filename": "expansion_fpds_2000_2004_vendor.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2000,
        "year_end": 2004,
        "filter_type": "vendor",
        "filters": {
            "Vendor Address State": "PR",
            "Date Signed": "10/01/2000 to 09/30/2004",
        },
        "description": "FPDS contracts with PR-based vendors, FY2000-2004",
    },
    {
        "filename": "expansion_fpds_2005_2008_direct.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2005,
        "year_end": 2008,
        "filter_type": "direct",
        "filters": {
            "Place of Performance State": "PR",
            "Date Signed": "10/01/2004 to 09/30/2008",
        },
        "description": "FPDS contracts performed in Puerto Rico, FY2005-2008 (CRITICAL: must contain 2007)",
    },
    {
        "filename": "expansion_fpds_2005_2008_vendor.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2005,
        "year_end": 2008,
        "filter_type": "vendor",
        "filters": {
            "Vendor Address State": "PR",
            "Date Signed": "10/01/2004 to 09/30/2008",
        },
        "description": "FPDS contracts with PR-based vendors, FY2005-2008 (CRITICAL: must contain 2007)",
    },
    {
        "filename": "expansion_fpds_2009_2016_direct.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2009,
        "year_end": 2016,
        "filter_type": "direct",
        "filters": {
            "Place of Performance State": "PR",
            "Date Signed": "10/01/2008 to 09/30/2016",
        },
        "description": "FPDS contracts performed in Puerto Rico, FY2009-2016",
    },
    {
        "filename": "expansion_fpds_2009_2016_vendor.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2009,
        "year_end": 2016,
        "filter_type": "vendor",
        "filters": {
            "Vendor Address State": "PR",
            "Date Signed": "10/01/2008 to 09/30/2016",
        },
        "description": "FPDS contracts with PR-based vendors, FY2009-2016",
    },
    {
        "filename": "expansion_fpds_2017_2025_direct.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2017,
        "year_end": 2025,
        "filter_type": "direct",
        "filters": {
            "Place of Performance State": "PR",
            "Date Signed": "10/01/2016 to 09/30/2025",
        },
        "description": "FPDS contracts performed in Puerto Rico, FY2017-2025",
    },
    {
        "filename": "expansion_fpds_2017_2025_vendor.csv",
        "source": "FPDS",
        "url": "https://www.fpds.gov/ezsearch/search.do",
        "year_start": 2017,
        "year_end": 2025,
        "filter_type": "vendor",
        "filters": {
            "Vendor Address State": "PR",
            "Date Signed": "10/01/2016 to 09/30/2025",
        },
        "description": "FPDS contracts with PR-based vendors, FY2017-2025",
    },
    # ---- USASpending: IDV / Indirect PR ----
    {
        "filename": "expansion_idv_indirect_pr.csv",
        "source": "USASpending",
        "url": "https://www.usaspending.gov/search",
        "year_start": 2000,
        "year_end": 2025,
        "filter_type": "idv",
        "filters": {
            "Award Type": "IDV / Delivery Order",
            "Recipient State": "NOT PR",
            "Keyword": "Puerto Rico",
        },
        "description": "USASpending IDV awards referencing Puerto Rico with non-PR recipients",
    },
    # ---- USASpending: DOD Corridor (split at 2015) ----
    {
        "filename": "expansion_dod_upr_2001_2015.csv",
        "source": "USASpending",
        "url": "https://www.usaspending.gov/search",
        "year_start": 2001,
        "year_end": 2015,
        "filter_type": "dod",
        "filters": {
            "Agency": "Department of Defense",
            "Keywords": [
                "Puerto Rico",
                "University of Puerto Rico",
                "Mayaguez",
                "Ramey",
                "Roosevelt Roads",
            ],
            "Time Period": "2001-2015",
        },
        "description": "USASpending DoD contracts related to PR (UPR, bases), 2001-2015",
    },
    {
        "filename": "expansion_dod_upr_2016_2025.csv",
        "source": "USASpending",
        "url": "https://www.usaspending.gov/search",
        "year_start": 2016,
        "year_end": 2025,
        "filter_type": "dod",
        "filters": {
            "Agency": "Department of Defense",
            "Keywords": [
                "Puerto Rico",
                "University of Puerto Rico",
                "Mayaguez",
                "Ramey",
                "Roosevelt Roads",
            ],
            "Time Period": "2016-2025",
        },
        "description": "USASpending DoD contracts related to PR (UPR, bases), 2016-2025",
    },
    # ---- Reconstruction Layer (Post-2017) ----
    {
        "filename": "expansion_reconstruction_2017_2025.csv",
        "source": "USASpending",
        "url": "https://www.usaspending.gov/search",
        "year_start": 2017,
        "year_end": 2025,
        "filter_type": "reconstruction",
        "filters": {
            "Agencies": ["FEMA", "HUD", "DOT", "USACE", "VA"],
            "Keywords": ["Puerto Rico", "Maria", "reconstruction"],
            "Time Period": "2017-2025",
        },
        "description": "USASpending reconstruction contracts (FEMA/HUD/DOT/USACE/VA), 2017-2025",
    },
    # ---- FSRS Subcontracts ----
    {
        "filename": "expansion_subcontracts_pr.csv",
        "source": "FSRS",
        "url": "https://www.fsrs.gov",
        "year_start": 2000,
        "year_end": 2025,
        "filter_type": "subcontract",
        "filters": {
            "Place of Performance": "Puerto Rico",
        },
        "description": "FSRS sub-award data with place of performance in Puerto Rico",
    },
]

# ---------------------------------------------------------------------------
# Column families — flexible name matching across sources
# ---------------------------------------------------------------------------

COLUMN_FAMILIES = {
    "date": [
        "date_signed",
        "Date Signed",
        "action_date",
        "Action Date",
        "Award Date",
        "Start Date",
        "period_of_performance_start_date",
        "Period of Performance Start Date",
        "Period of Performance\nStart Date",
        "subaward_date",
        "Date Submitted",
        "last_modified_date",
        "Last Modified Date",
    ],
    "vendor": [
        "vendorname",
        "Vendor Name",
        "vendor_name",
        "Recipient Name",
        "recipient_name",
        "company_name",
        "Sub-Awardee Name",
        "Recipient/Vendor Name",
    ],
    "agency": [
        "contracting_agency_name",
        "Contracting Agency Name",
        "Awarding Agency",
        "awarding_agency_name",
        "Awarding Agency Name",
        "funding_agency_name",
        "Funding Agency",
        "Funding Agency Name",
        "maj_agency_cat",
        "Agency Name",
        "Awarding Sub Agency",
    ],
    "amount": [
        "dollars_obligated",
        "Dollars Obligated",
        "obligatedAmount",
        "Award Amount",
        "total_obligation",
        "federal_action_obligation",
        "Federal Action Obligation",
        "subaward_amount",
        "Sub-Award Amount",
        "current_total_value_of_award",
        "Total Obligation",
        "Current Award Amount",
    ],
    "contract_id": [
        "piid",
        "PIID",
        "Award ID",
        "award_id_piid",
        "prime_award_piid",
        "contract_number",
        "Contract Number",
        "referenced_idv_piid",
        "idvpiid",
        "Award Unique Key",
    ],
    "pop_state": [
        "pop_state_code",
        "Place of Performance State",
        "Place of Performance State Code",
        "pop_state_name",
        "principalplaceofperformancestatecode",
        "primary_place_of_performance_state_code",
        "Primary Place of Performance State Code",
        "Sub-Award Place of Performance State",
    ],
}

STANDARD_COLUMNS = [
    "contract_id",
    "award_date",
    "vendor_name",
    "agency_name",
    "obligated_amount",
    "pop_state",
    "source_file",
    "fiscal_year",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_column_name(col: str) -> str:
    """Strip whitespace, BOM markers, and normalize newlines in a column name."""
    return col.strip().lstrip("\ufeff").replace("\n", " ").replace("\r", "")


def find_column(df_columns: list, family: str) -> str | None:
    """
    Find the first matching column name for a given family.
    Uses case-insensitive comparison against COLUMN_FAMILIES.
    Returns the actual column name from df_columns, or None.
    """
    candidates = COLUMN_FAMILIES.get(family, [])
    # Build a lowercase lookup from actual columns
    lower_map = {clean_column_name(c).lower(): c for c in df_columns}
    for candidate in candidates:
        key = candidate.lower().strip()
        if key in lower_map:
            return lower_map[key]
    return None


def read_csv_safe(filepath, nrows=None):
    """
    Read a CSV with encoding fallback chain: utf-8-sig -> utf-8 -> latin-1 -> cp1252.
    Returns a DataFrame or raises on total failure.
    """
    import pandas as pd

    import warnings as _warnings

    encodings = ["utf-8-sig", "utf-8", "latin-1", "cp1252"]
    last_err = None
    for enc in encodings:
        try:
            with _warnings.catch_warnings(record=True) as caught:
                _warnings.simplefilter("always")
                df = pd.read_csv(
                    filepath,
                    encoding=enc,
                    low_memory=False,
                    dtype=str,
                    nrows=nrows,
                    on_bad_lines="warn",
                )
            if caught:
                logging.getLogger("csv_reader").warning(
                    f"{Path(filepath).name}: {len(caught)} parse warning(s) ({enc} encoding)"
                )
            # Clean column names
            df.columns = [clean_column_name(c) for c in df.columns]
            return df
        except UnicodeDecodeError as e:
            last_err = e
            continue
        except Exception as e:
            last_err = e
            break
    raise RuntimeError(f"Failed to read {filepath}: {last_err}")


def setup_logging(log_name: str, log_dir: Path = None) -> logging.Logger:
    """
    Set up a logger that writes to stdout and a log file.
    Creates log directory if needed.
    """
    if log_dir is None:
        log_dir = LOGS_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(log_name)
    logger.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated calls
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    # File handler
    fh = logging.FileHandler(log_dir / f"{log_name}.log", mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


def get_expected_filenames() -> list:
    """Return list of expected expansion filenames."""
    return [m["filename"] for m in DOWNLOAD_MANIFEST]


def get_normalized_filename(expansion_filename: str) -> str:
    """Convert expansion filename to normalized filename."""
    return f"normalized_{expansion_filename}"


def _load_dotenv(path: Path) -> dict:
    """Minimal .env parser: KEY=value per line, ignores comments and blanks."""
    out = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def get_sam_api_key() -> str:
    """Return SAM.gov API key from SAM_API_KEY env var or .env file. Raises if missing."""
    import os
    key = os.environ.get("SAM_API_KEY", "").strip()
    if key:
        return key
    parsed = _load_dotenv(PROJECT_ROOT / ".env")
    key = parsed.get("SAM_API_KEY", "").strip()
    if key:
        return key
    raise RuntimeError(
        "SAM_API_KEY not found. Set it one of two ways:\n"
        "  1. export SAM_API_KEY=your_key_here\n"
        f"  2. Create {PROJECT_ROOT / '.env'} containing: SAM_API_KEY=your_key_here\n"
        "Get a free key at https://sam.gov/data-services"
    )
