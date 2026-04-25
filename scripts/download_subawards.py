"""
Download USASpending subawards where place of performance or prime recipient
is in Puerto Rico.

Uses the same spending_by_award endpoint as other downloads but with
subawards=true. Award type codes cover both grants (02-05) and contracts (A-D).

Time windows:
  FY2000-2009, FY2010-2017, FY2018-2022, FY2023-2026

Output:
  data/staging/raw/subawards/subawards_<start>f<end>.csv  (raw per-window)
  data/staging/processed/pr_subawards_master.csv          (deduplicated master)

Usage:
  python3 scripts/download_subawards.py                  # full run
  python3 scripts/download_subawards.py --force          # re-download existing
  python3 scripts/download_subawards.py --fy-start 2017  # only FY2017+
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

# Must be queried in separate passes — API rejects mixing grant and procurement codes
GRANT_TYPE_CODES = ["02", "03", "04", "05"]
CONTRACT_TYPE_CODES = ["A", "B", "C", "D"]

SUBAWARD_FIELDS = [
    "Sub-Award ID",
    "Sub-Awardee Name",
    "Sub-Award Amount",
    "Sub-Award Date",
    "Prime Award ID",
    "Prime Recipient Name",
    "Awarding Agency",
    "Place of Performance State Code",
    "Description",
]

# Four time windows (calendar start of FY → end of FY)
TIME_WINDOWS = [
    {"label": "2000f2009", "start_date": "2007-10-01", "end_date": "2009-09-30", "fy_start": 2000},
    {"label": "2010f2017", "start_date": "2010-10-01", "end_date": "2017-09-30", "fy_start": 2010},
    {"label": "2018f2022", "start_date": "2018-10-01", "end_date": "2022-09-30", "fy_start": 2018},
    {"label": "2023f2026", "start_date": "2023-10-01", "end_date": "2026-09-30", "fy_start": 2023},
]

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
    "prime_award_id",
    "prime_recipient_name",
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
    """Derive fiscal year from a date string (YYYY-MM-DD). Oct-Dec → year+1."""
    if not date_str or pd.isna(date_str):
        return ""
    try:
        d = pd.to_datetime(str(date_str), errors="coerce")
        if pd.isna(d):
            return ""
        return str(d.year + 1) if d.month >= 10 else str(d.year)
    except Exception:
        return ""


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
    """Paginate through all results for a given payload. Returns list of raw result dicts."""
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


def _build_payload(window: dict, type_codes: list) -> dict:
    """Build a spending_by_award subawards payload for the given time window and type group."""
    return {
        "filters": {
            "award_type_codes": type_codes,
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
            "time_period": [{"start_date": window["start_date"], "end_date": window["end_date"]}],
        },
        "fields": SUBAWARD_FIELDS,
        "page": 1,
        "limit": 100,
        "sort": "Sub-Award Amount",
        "order": "desc",
        "subawards": True,
    }


def _results_to_df(results: list[dict], source_file: str) -> pd.DataFrame:
    """Convert raw API results to a DataFrame with canonical master columns."""
    if not results:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    df = pd.json_normalize(results)

    # Field mapping: API name → master column name
    rename_map = {
        "Sub-Award ID": "award_id",
        "Sub-Awardee Name": "recipient_name",
        "Sub-Award Amount": "obligated_amount",
        "Sub-Award Date": "award_date",
        "Prime Award ID": "prime_award_id",
        "Prime Recipient Name": "prime_recipient_name",
        "Awarding Agency": "awarding_agency",
        "Place of Performance State Code": "pop_state",
        "Description": "description",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    # Derive fiscal_year
    if "award_date" in df.columns:
        df["fiscal_year"] = df["award_date"].apply(_derive_fiscal_year)
    else:
        df["fiscal_year"] = ""

    df["source_file"] = source_file
    df["source_dataset"] = "subawards"
    df["award_category"] = "subaward"

    # Ensure all master columns are present
    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[MASTER_COLUMNS]


def _file_has_data(filepath: Path) -> bool:
    """Return True if file exists and has at least one data row."""
    if not filepath.exists():
        return False
    try:
        df = pd.read_csv(filepath, dtype=str, nrows=2, low_memory=False)
        return len(df) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Core download logic
# ---------------------------------------------------------------------------

def download_window(
    session: requests.Session,
    window: dict,
    raw_dir: Path,
    force: bool,
    logger,
) -> dict:
    """Download subawards for one time window (two passes: grants then contracts)."""
    label = window["label"]
    stats = {"window": label, "grant_rows": 0, "contract_rows": 0, "errors": []}

    for type_group, type_codes in [
        ("grants", GRANT_TYPE_CODES),
        ("contracts", CONTRACT_TYPE_CODES),
    ]:
        fname = f"subawards_{type_group}_{label}.csv"
        fpath = raw_dir / fname

        if not force and _file_has_data(fpath):
            try:
                existing = pd.read_csv(fpath, dtype=str, low_memory=False)
                rows = len(existing)
            except Exception:
                rows = 0
            logger.info(f"  Skipping {fname} (exists, {rows} rows)")
            stats[f"{type_group}_rows"] = rows
            continue

        logger.info(
            f"  Fetching {fname} ({window['start_date']} to {window['end_date']}, type={type_group})"
        )
        payload = _build_payload(window, type_codes)
        results = _paginate(session, payload, logger)

        if not results:
            logger.warning(f"  No results for {fname}")
            stats["errors"].append(f"{fname}: no results")
            pd.DataFrame(columns=MASTER_COLUMNS).to_csv(fpath, index=False, encoding="utf-8")
            continue

        df = _results_to_df(results, fname)
        raw_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(fpath, index=False, encoding="utf-8")
        stats[f"{type_group}_rows"] = len(df)
        logger.info(f"  Saved {len(df)} rows → {fname}")

    return stats


# ---------------------------------------------------------------------------
# Master build
# ---------------------------------------------------------------------------

def build_master(raw_dir: Path, master_path: Path, logger) -> int:
    """Concatenate all raw subaward CSVs, deduplicate by award_id, write master."""
    files = sorted(raw_dir.glob("subawards_*.csv"))
    if not files:
        logger.warning("  No raw subaward files found — master not written")
        return 0

    frames = []
    for f in files:
        try:
            df = pd.read_csv(f, dtype=str, low_memory=False)
            frames.append(df)
            logger.debug(f"  Loaded {f.name}: {len(df)} rows")
        except Exception as e:
            logger.warning(f"  Skipping {f.name}: {e}")

    if not frames:
        logger.warning("  No data loaded — master not written")
        return 0

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    logger.info(f"  Combined: {before:,} rows before dedup")

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
    """Main entry point. Returns summary dict."""
    return _run(root=root, force=False, fy_start=None)


def _run(root: Path = None, force: bool = False, fy_start: int = None) -> dict:
    """Internal runner used by both run() and main()."""
    if root is None:
        root = PROJECT_ROOT

    raw_dir = root / "data" / "staging" / "raw" / "subawards"
    master_path = root / "data" / "staging" / "processed" / "pr_subawards_master.csv"

    raw_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_subawards")
    logger.info("Starting PR subawards download...")

    windows = TIME_WINDOWS
    if fy_start is not None:
        windows = [w for w in TIME_WINDOWS if w["fy_start"] >= fy_start]
        if not windows:
            logger.warning(f"  No time windows with fy_start >= {fy_start}")

    session = _session()
    all_errors = []
    total_rows = 0
    window_stats = []

    for window in windows:
        logger.info(f"[Window {window['label']}] {window['start_date']} to {window['end_date']}")
        try:
            stats = download_window(session, window, raw_dir, force, logger)
        except Exception as e:
            logger.error(f"  Unexpected error on window {window['label']}: {e}")
            stats = {"window": window["label"], "grant_rows": 0, "contract_rows": 0, "errors": [str(e)]}

        total_rows += stats.get("grant_rows", 0) + stats.get("contract_rows", 0)
        all_errors.extend(stats["errors"])
        window_stats.append(stats)
        logger.info("")

    session.close()

    logger.info("Building subawards master...")
    master_rows = build_master(raw_dir, master_path, logger)

    summary = {
        "raw_rows": total_rows,
        "master_rows": master_rows,
        "master_path": str(master_path),
        "raw_dir": str(raw_dir),
        "errors": all_errors,
        "windows": window_stats,
    }

    logger.info("=" * 60)
    logger.info("SUBAWARDS DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Raw rows:    {total_rows:,}")
    logger.info(f"  Master rows: {master_rows:,}")
    logger.info(f"  Errors:      {len(all_errors)}")
    if all_errors:
        for err in all_errors:
            logger.warning(f"    {err}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download USASpending subawards for Puerto Rico"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download existing raw files",
    )
    parser.add_argument(
        "--fy-start",
        type=int,
        metavar="YEAR",
        help="Only download windows with fy_start >= YEAR (e.g. 2017)",
    )
    args = parser.parse_args()

    summary = _run(force=args.force, fy_start=args.fy_start)

    print(f"\nSubawards download complete.")
    print(f"  Raw rows:    {summary['raw_rows']:,}")
    print(f"  Master rows: {summary['master_rows']:,}")
    print(f"  Master path: {summary['master_path']}")
    if summary["errors"]:
        print(f"  Errors ({len(summary['errors'])}):")
        for err in summary["errors"]:
            print(f"    {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
