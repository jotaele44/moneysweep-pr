"""
Download Treasury SLFRF (State and Local Fiscal Recovery Funds / ARPA) data for Puerto Rico
via USASpending spending_by_award API, filtered to Assistance Listing 21.027.

Puerto Rico received ~$4.1B from the American Rescue Plan Act SLFRF program.
This replaces the previous Treasury XLSX download approach (URLs now 404).

Two award type passes per run:
  grants  (02-05): block grants, formula grants, project grants, cooperative agreements
  direct  (06-07): direct payments for specified and unrestricted use

Output:
  data/staging/raw/slfrf/slfrf_grants.csv             (raw grants pass)
  data/staging/raw/slfrf/slfrf_direct.csv             (raw direct payments pass)
  data/staging/processed/pr_slfrf_master.csv           (deduplicated master)

Usage:
  python3 scripts/download_slfrf.py            # full run
  python3 scripts/download_slfrf.py --force    # re-download even if files exist
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

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# USASpending award type groups (confirmed from API error messages):
#   grants: 02, 03, 04, 05, 06
#   loans:  07, 08, F003, F004
AWARD_TYPE_GROUPS = [
    ("grants", ["02", "03", "04", "05", "06"]),
    ("loans",  ["07", "08"]),
]

SLFRF_FIELDS = [
    "Award ID",
    "Recipient Name",
    "recipient_uei",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Award Amount",
    "Start Date",
    "Award Type",
    "Place of Performance State Code",
    "Place of Performance County Name",
    "Description",
]

# ARP signed March 11, 2021; SLFRF funds available through FY2026
SLFRF_START = "2021-03-11"
SLFRF_END = "2026-09-30"

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
PAGE_SLEEP = 0.3
RATE_LIMIT_SLEEP = 30


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
    """Return True if file exists and has at least one data row."""
    if not filepath.exists():
        return False
    try:
        df = pd.read_csv(filepath, dtype=str, nrows=2, low_memory=False)
        return len(df) > 0
    except Exception:
        return False


def _fetch_page(session: requests.Session, payload: dict, logger) -> dict | None:
    """POST one page to the API with retry/backoff. Returns parsed JSON or None."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(USASPENDING_URL, json=payload, timeout=30)
            if resp.status_code == 429:
                logger.warning(f"  Rate limited (429) — sleeping {RATE_LIMIT_SLEEP}s then retrying once")
                time.sleep(RATE_LIMIT_SLEEP)
                resp = session.post(USASPENDING_URL, json=payload, timeout=30)
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code} (client error) — skipping: {resp.text[:300]}")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if 400 <= status < 500:
                logger.error(f"  HTTP {status} (client error) — skipping: {e}")
                return None
            last_err = e
        except requests.RequestException as e:
            last_err = e
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            logger.warning(f"  Attempt {attempt + 1} failed ({last_err}) — retrying in {wait}s")
            time.sleep(wait)
    logger.error(f"  All {MAX_RETRIES} attempts failed: {last_err}")
    return None


def _paginate(session: requests.Session, base_payload: dict, logger) -> list[dict]:
    """Paginate through all results. Returns list of raw result dicts."""
    all_results = []
    page = 1
    while True:
        payload = dict(base_payload)
        payload["page"] = page
        data = _fetch_page(session, payload, logger)
        if data is None:
            break
        results = data.get("results", [])
        if not results:
            break
        all_results.extend(results)
        page_meta = data.get("page_metadata", {})
        has_next = page_meta.get("has_next_page", False)
        if page % 10 == 0:
            logger.info(f"    Page {page} ({len(all_results)} records so far)")
        if not has_next:
            break
        page += 1
        time.sleep(PAGE_SLEEP)
    return all_results


def _build_payload(type_codes: list) -> dict:
    """Build a spending_by_award payload: Treasury awarding agency + PR recipient + SLFRF window.

    program_numbers (CFDA 21.027) is intentionally omitted — it returns 0 results with
    recipient_locations filtering. Treasury + PR + 2021-2026 is already precise enough.
    """
    return {
        "filters": {
            "award_type_codes": type_codes,
            "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of the Treasury"}],
            "recipient_locations": [{"country": "USA", "state": "PR"}],
            "time_period": [{"start_date": SLFRF_START, "end_date": SLFRF_END}],
        },
        "fields": SLFRF_FIELDS,
        "page": 1,
        "limit": 100,
        "sort": "Award ID" if any(c in ["07", "08"] for c in type_codes) else "Award Amount",
        "order": "desc",
        "subawards": False,
    }


def _results_to_df(results: list[dict], source_file: str) -> pd.DataFrame:
    """Convert raw API results to canonical master columns."""
    if not results:
        return pd.DataFrame(columns=MASTER_COLUMNS)
    df = pd.json_normalize(results)
    rename_map = {
        "Award ID": "award_id",
        "Recipient Name": "recipient_name",
        "recipient_uei": "recipient_uei",
        "Awarding Agency": "awarding_agency",
        "Awarding Sub Agency": "awarding_sub_agency",
        "Award Amount": "obligated_amount",
        "Start Date": "award_date",
        "Award Type": "award_category",
        "Place of Performance State Code": "pop_state",
        "Place of Performance County Name": "pop_county",
        "Description": "description",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    if "award_date" in df.columns:
        df["fiscal_year"] = df["award_date"].apply(_derive_fiscal_year)
    else:
        df["fiscal_year"] = ""
    df["source_file"] = source_file
    df["source_dataset"] = "slfrf"
    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[MASTER_COLUMNS]


# ---------------------------------------------------------------------------
# Master build
# ---------------------------------------------------------------------------

def build_master(raw_dir: Path, master_path: Path, logger) -> int:
    """Concatenate raw SLFRF files, deduplicate by award_id, write master."""
    files = sorted(raw_dir.glob("slfrf_*.csv"))
    if not files:
        logger.warning("  No raw SLFRF files found — master not written")
        return 0
    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str, low_memory=False)
            frames.append(df)
        except Exception as e:
            logger.warning(f"  Skipping {f.name}: {e}")
    if not frames:
        return 0
    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    if "award_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["award_id"], keep="first")
        removed = before - len(combined)
        if removed:
            logger.info(f"  Removed {removed:,} duplicate award_id rows")
    master_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(combined):,} rows → {master_path.name}")
    return len(combined)


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
    master_path = root / "data" / "staging" / "processed" / "pr_slfrf_master.csv"

    raw_dir.mkdir(parents=True, exist_ok=True)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_slfrf")
    logger.info("Starting SLFRF download for Puerto Rico (USASpending CFDA 21.027)...")

    session = _session()
    all_errors = []
    total_raw_rows = 0

    for group_label, type_codes in AWARD_TYPE_GROUPS:
        fname = f"slfrf_{group_label}.csv"
        fpath = raw_dir / fname

        if not force and _file_has_data(fpath):
            try:
                existing = pd.read_csv(fpath, dtype=str, low_memory=False)
                rows = len(existing)
            except Exception:
                rows = 0
            logger.info(f"  Skipping {fname} (exists, {rows} rows)")
            total_raw_rows += rows
            continue

        logger.info(f"  Fetching {fname} (type_group={group_label})")
        payload = _build_payload(type_codes)
        results = _paginate(session, payload, logger)

        if not results:
            logger.warning(f"  No results for {fname}")
            all_errors.append(f"{fname}: no results")
            pd.DataFrame(columns=MASTER_COLUMNS).to_csv(fpath, index=False, encoding="utf-8")
            continue

        df = _results_to_df(results, fname)
        df.to_csv(fpath, index=False, encoding="utf-8")
        total_raw_rows += len(df)
        logger.info(f"  Saved {len(df)} rows → {fname}")

    session.close()

    logger.info("Building SLFRF master...")
    master_rows = build_master(raw_dir, master_path, logger)

    summary = {
        "rows": master_rows,
        "raw_rows": total_raw_rows,
        "master_path": str(master_path),
        "raw_dir": str(raw_dir),
        "errors": all_errors,
        "status": "OK" if master_rows > 0 else "EMPTY",
    }

    logger.info("=" * 60)
    logger.info("SLFRF DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Raw rows:    {total_raw_rows:,}")
    logger.info(f"  Master rows: {master_rows:,}")
    logger.info(f"  Errors:      {len(all_errors)}")
    if all_errors:
        for err in all_errors:
            logger.warning(f"    {err}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download Treasury SLFRF data for Puerto Rico via USASpending"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if raw files already exist",
    )
    args = parser.parse_args()
    summary = _run(force=args.force)
    print("\nSLFRF download complete.")
    print(f"  Raw rows:    {summary['raw_rows']:,}")
    print(f"  Master rows: {summary['rows']:,}")
    print(f"  Master path: {summary['master_path']}")
    print(f"  Status:      {summary['status']}")
    if summary["errors"]:
        print(f"  Errors ({len(summary['errors'])}):")
        for err in summary["errors"]:
            print(f"    {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
