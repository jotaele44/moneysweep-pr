"""
Download SBIR/STTR (Small Business Innovation Research / Technology Transfer) awards
for Puerto Rico from the sbir.gov public API.

Awards to PR-based small businesses from all federal agencies (DoD, NIH, NSF, NASA,
DOE, etc.) that participate in the SBIR/STTR programs.

Output:
  data/staging/raw/sbir/sbir_pr.csv
  data/staging/processed/pr_sbir_master.csv

Usage:
  python3 scripts/download_sbir.py
  python3 scripts/download_sbir.py --force
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

SBIR_API_URL = "https://api.sbir.gov/public/awards"

# Fallback: older sbir.gov search endpoint
SBIR_SEARCH_URL = "https://www.sbir.gov/api/awards.json"

PAGE_SIZE = 100
PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]

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


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_fiscal_year(year_val) -> str:
    if not year_val or pd.isna(year_val):
        return ""
    try:
        return str(int(float(str(year_val))))
    except Exception:
        return ""


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    """GET with retry/backoff. Returns parsed JSON or None."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 30s")
                time.sleep(30)
                resp = session.get(url, params=params, timeout=60)
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code} — skipping: {resp.text[:200]}")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            logger.warning(f"  Attempt {attempt + 1} failed ({last_err}) — retrying in {wait}s")
            time.sleep(wait)
    logger.error(f"  All {MAX_RETRIES} attempts failed: {last_err}")
    return None


def _paginate(session: requests.Session, logger) -> list[dict]:
    """
    Paginate sbir.gov awards API for PR firms.
    Tries api.sbir.gov first, falls back to www.sbir.gov.
    """
    all_records = []

    for base_url, count_field, data_field, start_param in [
        (SBIR_API_URL,    "totalCount", "data",    "start"),
        (SBIR_SEARCH_URL, "total",      "results", "start"),
    ]:
        logger.info(f"  Trying endpoint: {base_url}")
        params = {"firm_state": "PR", "count": PAGE_SIZE, "start": 0}
        data = _get(session, base_url, params, logger)
        if data is None:
            continue

        # Handle both list response and dict response
        if isinstance(data, list):
            records = data
            total = len(records)
            logger.info(f"  Got list response: {total} records (no pagination)")
            all_records.extend(records)
            break

        if isinstance(data, dict):
            total = data.get(count_field, 0) or data.get("total", 0) or 0
            records = data.get(data_field, []) or data.get("awards", []) or []
            if not records and not total:
                logger.warning(f"  Empty response from {base_url} — trying next endpoint")
                continue
            logger.info(f"  Total SBIR/STTR awards for PR: {total:,}")
            all_records.extend(records)

            # Paginate remaining pages
            offset = PAGE_SIZE
            while offset < total:
                params[start_param] = offset
                page_data = _get(session, base_url, params, logger)
                if page_data is None:
                    break
                if isinstance(page_data, list):
                    page_records = page_data
                else:
                    page_records = page_data.get(data_field, []) or page_data.get("awards", []) or []
                if not page_records:
                    break
                all_records.extend(page_records)
                if len(all_records) % 500 == 0:
                    logger.info(f"  Fetched {len(all_records):,} / {total:,}")
                offset += PAGE_SIZE
                time.sleep(PAGE_SLEEP)
            break

    return all_records


def _records_to_df(records: list[dict], source_file: str) -> pd.DataFrame:
    """Normalize raw sbir.gov records to canonical master columns."""
    if not records:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    df = pd.json_normalize(records)

    def col(*candidates):
        for c in candidates:
            if c in df.columns:
                return df[c].fillna("")
        return pd.Series("", index=df.index)

    # Build award_id from contract number or a composite
    contract = col("contract", "award_id", "solicitation_number")
    program = col("program", "program_name")
    df["award_id"] = "SBIR-" + contract.where(contract.str.strip() != "",
                                               other=df.index.astype(str))

    df["recipient_name"]      = col("firm", "company", "recipient_name")
    df["recipient_uei"]       = col("uei", "recipient_uei")
    df["awarding_agency"]     = col("agency", "awarding_agency")
    df["awarding_sub_agency"] = col("branch", "program_name")
    df["obligated_amount"]    = col("amount", "award_amount")
    df["award_date"]          = col("award_date", "date_signed")
    df["fiscal_year"]         = col("award_year", "fiscal_year").apply(_derive_fiscal_year)
    df["pop_state"]           = "PR"
    df["pop_county"]          = col("place_name", "city")
    df["description"]         = col("award_title", "abstract", "title")
    df["source_file"]         = source_file
    df["source_dataset"]      = "sbir"
    df["award_category"]      = "grant"

    for c in MASTER_COLUMNS:
        if c not in df.columns:
            df[c] = ""

    return df[MASTER_COLUMNS]


def _file_has_data(filepath: Path) -> bool:
    if not filepath.exists():
        return False
    try:
        return len(pd.read_csv(filepath, dtype=str, nrows=2, low_memory=False)) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run(root: Path = None) -> dict:
    return _run(root=root, force=False)


def _run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    raw_dir = root / "data" / "staging" / "raw" / "sbir"
    raw_path = raw_dir / "sbir_pr.csv"
    master_path = root / "data" / "staging" / "processed" / "pr_sbir_master.csv"

    raw_dir.mkdir(parents=True, exist_ok=True)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_sbir")
    logger.info("Starting SBIR/STTR download for Puerto Rico...")

    if not force and _file_has_data(raw_path):
        logger.info(f"  Raw file exists — loading for master build")
        records = pd.read_csv(raw_path, dtype=str, low_memory=False).to_dict("records")
    else:
        session = _session()
        records = _paginate(session, logger)
        session.close()

        if records:
            df_raw = pd.json_normalize(records)
            raw_dir.mkdir(parents=True, exist_ok=True)
            df_raw.to_csv(raw_path, index=False, encoding="utf-8")
            logger.info(f"  Saved {len(records):,} raw records → {raw_path.name}")
        else:
            logger.warning("  No SBIR/STTR records returned — writing empty master")
            pd.DataFrame(columns=MASTER_COLUMNS).to_csv(master_path, index=False, encoding="utf-8")
            return {"rows": 0, "raw_rows": 0, "master_path": str(master_path), "status": "EMPTY"}

    master = _records_to_df(records, raw_path.name)
    master = master.drop_duplicates(subset=["award_id"], keep="first")
    master.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(master):,} rows → {master_path.name}")

    summary = {
        "rows": len(master),
        "raw_rows": len(records),
        "master_path": str(master_path),
        "status": "OK" if len(master) > 0 else "EMPTY",
    }

    logger.info("=" * 60)
    logger.info("SBIR DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Raw rows:    {summary['raw_rows']:,}")
    logger.info(f"  Master rows: {summary['rows']:,}")
    logger.info(f"  Status:      {summary['status']}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download SBIR/STTR awards for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    summary = _run(force=args.force)
    print(f"\nSBIR download complete.")
    print(f"  Raw rows:    {summary['raw_rows']:,}")
    print(f"  Master rows: {summary['rows']:,}")
    print(f"  Status:      {summary['status']}")
    return 0 if summary["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
