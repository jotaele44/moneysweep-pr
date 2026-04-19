"""
Download Treasury SLFRF (State and Local Fiscal Recovery Funds / ARPA) data for Puerto Rico.

Puerto Rico received ~$4.1B from the American Rescue Plan Act SLFRF program.

Approach:
  1. Attempt to download the Treasury SLFRF public recipient compliance Excel file.
  2. Parse the Puerto Rico sheet or filter rows for Puerto Rico.
  3. If download fails, write an empty master with headers and log instructions.

Output:
  data/staging/raw/slfrf/slfrf_raw.xlsx           (downloaded Excel file)
  data/staging/processed/pr_slfrf_master.csv       (canonical master)

Usage:
  python3 scripts/download_slfrf.py            # full run
  python3 scripts/download_slfrf.py --force    # re-download even if file exists
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SLFRF_DOWNLOAD_URLS = [
    "https://home.treasury.gov/system/files/136/SLFRF_Recipient_Compliance_and_Performance_Report_Data.xlsx",
    "https://home.treasury.gov/system/files/136/SLFRF-Recipient-Compliance-and-Reporting-Guidance.xlsx",
]

MANUAL_DOWNLOAD_URL = (
    "https://home.treasury.gov/policy-issues/coronavirus/assistance-for-state-local-and-tribal-governments"
    "/state-and-local-fiscal-recovery-funds/public-data"
)

MANUAL_DOWNLOAD_MSG = (
    f"SLFRF data requires manual download from {MANUAL_DOWNLOAD_URL} "
    "— Download the 'Recipient Payments' Excel and save to data/staging/raw/slfrf/"
)

PR_STATE_VALUES = {"pr", "puerto rico", "72"}

MASTER_COLUMNS = [
    "award_id",
    "recipient_name",
    "recipient_uei",
    "awarding_agency",
    "awarding_sub_agency",
    "obligated_amount",
    "award_date",
    "fiscal_year",
    "pop_state",
    "pop_county",
    "description",
    "source_file",
    "source_dataset",
    "award_category",
]

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0"})
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_fiscal_year(date_str) -> str:
    """Derive US fiscal year from a date string. Oct-Dec → year+1."""
    if not date_str or pd.isna(date_str):
        return ""
    try:
        d = pd.to_datetime(str(date_str), errors="coerce")
        if pd.isna(d):
            return ""
        return str(d.year + 1) if d.month >= 10 else str(d.year)
    except Exception:
        return ""


def _file_has_data(filepath: Path) -> bool:
    """Return True if file exists and has a non-zero size."""
    return filepath.exists() and filepath.stat().st_size > 0


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def _download_excel(raw_path: Path, logger) -> bool:
    """
    Try each known URL in order. Stream-write to raw_path on success.
    Returns True if download succeeded, False otherwise.
    """
    session = _session()
    for url in SLFRF_DOWNLOAD_URLS:
        logger.info(f"  Trying SLFRF download: {url}")
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = session.get(url, stream=True, timeout=120)
                if resp.status_code == 200:
                    raw_path.parent.mkdir(parents=True, exist_ok=True)
                    with open(raw_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=65536):
                            if chunk:
                                f.write(chunk)
                    logger.info(f"  Downloaded {raw_path.stat().st_size:,} bytes → {raw_path.name}")
                    session.close()
                    return True
                else:
                    logger.warning(f"  HTTP {resp.status_code} from {url}")
                    break  # No point retrying a 4xx
            except requests.RequestException as e:
                last_err = e
                if attempt < MAX_RETRIES - 1:
                    wait = RETRY_BACKOFF[attempt]
                    logger.warning(f"  Attempt {attempt + 1} failed ({e}) — retrying in {wait}s")
                    time.sleep(wait)
        if last_err:
            logger.warning(f"  All attempts failed for {url}: {last_err}")

    session.close()
    return False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def _is_pr_row(value) -> bool:
    """Return True if a state/recipient field looks like Puerto Rico."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return str(value).strip().lower() in PR_STATE_VALUES


def _find_pr_sheet(xl: pd.ExcelFile, logger) -> str | None:
    """
    Return a sheet name that likely contains Puerto Rico data.
    Prefers exact 'Puerto Rico' match, then case-insensitive partial match.
    """
    for sheet in xl.sheet_names:
        if sheet.strip().lower() == "puerto rico":
            logger.info(f"  Found 'Puerto Rico' sheet: '{sheet}'")
            return sheet
    for sheet in xl.sheet_names:
        if "puerto" in sheet.lower() or "rico" in sheet.lower():
            logger.info(f"  Found partial PR sheet match: '{sheet}'")
            return sheet
    return None


def _col(df: pd.DataFrame, *candidates) -> pd.Series:
    """Return first matching column Series, or empty string Series."""
    for c in candidates:
        if c in df.columns:
            return df[c]
    return pd.Series("", index=df.index)


def _parse_excel(raw_path: Path, logger) -> pd.DataFrame:
    """
    Read the SLFRF Excel, find Puerto Rico data, and return a canonical master DataFrame.
    """
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        logger.error("openpyxl is not installed — run: pip install openpyxl")
        return pd.DataFrame(columns=MASTER_COLUMNS)

    logger.info(f"  Reading Excel: {raw_path.name}")
    try:
        xl = pd.ExcelFile(raw_path, engine="openpyxl")
    except Exception as e:
        logger.error(f"  Failed to open Excel file: {e}")
        return pd.DataFrame(columns=MASTER_COLUMNS)

    logger.info(f"  Sheets found: {xl.sheet_names}")

    # Strategy 1: dedicated Puerto Rico sheet
    pr_sheet = _find_pr_sheet(xl, logger)
    if pr_sheet:
        try:
            df = xl.parse(pr_sheet, dtype=str)
            logger.info(f"  Read {len(df):,} rows from sheet '{pr_sheet}'")
            return _normalize_slfrf(df, raw_path.name, logger)
        except Exception as e:
            logger.warning(f"  Failed to parse sheet '{pr_sheet}': {e}")

    # Strategy 2: scan all sheets for rows mentioning Puerto Rico
    all_frames = []
    state_candidates = [
        "State", "state", "Recipient State", "recipient_state",
        "State Name", "State Code", "Recipient Name",
    ]

    for sheet in xl.sheet_names:
        try:
            df = xl.parse(sheet, dtype=str)
            if df.empty:
                continue
            # Find a column that might contain state info
            for col_name in state_candidates:
                if col_name in df.columns:
                    mask = df[col_name].apply(_is_pr_row)
                    pr_rows = df[mask]
                    if len(pr_rows) > 0:
                        logger.info(
                            f"  Sheet '{sheet}': found {len(pr_rows):,} PR rows via column '{col_name}'"
                        )
                        all_frames.append(pr_rows)
                    break
        except Exception as e:
            logger.warning(f"  Could not parse sheet '{sheet}': {e}")

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        logger.info(f"  Total PR rows across all sheets: {len(combined):,}")
        return _normalize_slfrf(combined, raw_path.name, logger)

    logger.warning(
        "  No Puerto Rico rows found in any sheet. "
        "The file may not contain recipient-level data or may use a different format."
    )
    return pd.DataFrame(columns=MASTER_COLUMNS)


def _normalize_slfrf(df: pd.DataFrame, source_file: str, logger) -> pd.DataFrame:
    """Map raw SLFRF DataFrame rows to canonical master columns."""
    if df.empty:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    rows = []
    for i, row in df.iterrows():
        recipient_name = (
            _col(df, "Recipient Name", "Recipient", "recipient_name",
                 "Entity Name", "Subrecipient Name").iloc[0]
            if len(df) == 1
            else row.get("Recipient Name", row.get("Recipient", row.get("recipient_name",
                row.get("Entity Name", row.get("Subrecipient Name", "")))))
        )
        description = (
            row.get("Project Name", row.get("Expenditure Category",
            row.get("Project Description", row.get("Category", ""))))
        )
        obligated_amount = (
            row.get("Amount Obligated", row.get("Amount Expended",
            row.get("Total Obligation", row.get("Federal Funding Amount",
            row.get("Total Expenditures", "")))))
        )
        award_date = (
            row.get("Reporting Period", row.get("Period of Performance",
            row.get("Date", row.get("Report Date", ""))))
        )
        award_id = f"SLFRF-{i}"

        rows.append({
            "award_id": award_id,
            "recipient_name": str(recipient_name).strip() if recipient_name else "",
            "recipient_uei": str(row.get("UEI", row.get("SAM UEI", ""))).strip(),
            "awarding_agency": "Department of the Treasury",
            "awarding_sub_agency": "",
            "obligated_amount": str(obligated_amount).strip() if obligated_amount else "",
            "award_date": str(award_date).strip() if award_date else "",
            "fiscal_year": _derive_fiscal_year(award_date),
            "pop_state": "PR",
            "pop_county": str(row.get("County", row.get("Municipality", ""))).strip(),
            "description": str(description).strip() if description else "",
            "source_file": source_file,
            "source_dataset": "slfrf",
            "award_category": "direct_payment",
        })

    master = pd.DataFrame(rows, columns=MASTER_COLUMNS)
    logger.info(f"  Normalized {len(master):,} SLFRF rows for Puerto Rico")
    return master


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run(root: Path = None) -> dict:
    """Main entry point (no --force). Returns summary dict."""
    return _run(root=root, force=False)


def _run(root: Path = None, force: bool = False) -> dict:
    """Internal runner used by both run() and main()."""
    if root is None:
        root = PROJECT_ROOT

    raw_dir = root / "data" / "staging" / "raw" / "slfrf"
    raw_path = raw_dir / "slfrf_raw.xlsx"
    master_path = root / "data" / "staging" / "processed" / "pr_slfrf_master.csv"

    raw_dir.mkdir(parents=True, exist_ok=True)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_slfrf")
    logger.info("Starting SLFRF download for Puerto Rico...")

    # ------------------------------------------------------------------
    # Skip download if file already exists and not forcing
    # ------------------------------------------------------------------
    downloaded_ok = False
    if not force and _file_has_data(raw_path):
        logger.info(f"  Raw file already exists ({raw_path.name}) — using existing file")
        downloaded_ok = True
    else:
        downloaded_ok = _download_excel(raw_path, logger)

    # ------------------------------------------------------------------
    # Parse or emit manual-download notice
    # ------------------------------------------------------------------
    if downloaded_ok and _file_has_data(raw_path):
        master = _parse_excel(raw_path, logger)
    else:
        logger.warning(MANUAL_DOWNLOAD_MSG)
        master = pd.DataFrame(columns=MASTER_COLUMNS)

    # ------------------------------------------------------------------
    # Write master (always — even if empty — so downstream doesn't fail)
    # ------------------------------------------------------------------
    master.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(master):,} rows → {master_path.name}")

    status = "OK" if len(master) > 0 else "MANUAL_DOWNLOAD_REQUIRED"

    summary: dict = {
        "rows": len(master),
        "master_path": str(master_path),
        "raw_path": str(raw_path),
        "status": status,
    }
    if status == "MANUAL_DOWNLOAD_REQUIRED":
        summary["instructions"] = MANUAL_DOWNLOAD_MSG

    logger.info("=" * 60)
    logger.info("SLFRF DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Master rows: {summary['rows']:,}")
    logger.info(f"  Status:      {summary['status']}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Treasury SLFRF data for Puerto Rico"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if raw file already exists",
    )
    args = parser.parse_args()

    summary = _run(force=args.force)

    print("\nSLFRF download complete.")
    print(f"  Master rows: {summary['rows']:,}")
    print(f"  Master path: {summary['master_path']}")
    print(f"  Status:      {summary['status']}")
    if "instructions" in summary:
        print(f"\n  NOTE: {summary['instructions']}")
    return 0 if summary["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
