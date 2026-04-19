"""
Download HUD (regular CDBG + HOME + other) grants to/in Puerto Rico from USASpending.

Covers: Community Development Block Grant (annual formula, NOT disaster recovery),
HOME Investment Partnerships, Section 108 loan guarantees, and other HUD
assistance programs. HUD CDBG-DR is already captured by download_cdbg_dr.py.

Two filter passes per time window:
  - place_of_performance_locations: work performed in PR
  - recipient_locations: PR-based recipients

Time windows: FY2000-2009, FY2010-2017, FY2018-2022, FY2023-2025

Output:
  data/staging/raw/hud/hud_pop_<label>.csv
  data/staging/raw/hud/hud_recipient_<label>.csv
  data/staging/processed/pr_hud_master.csv

Usage:
  python3 scripts/download_hud.py
  python3 scripts/download_hud.py --force
  python3 scripts/download_hud.py --fy-start 2017
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

AGENCY_NAME = "Department of Housing and Urban Development"
GRANT_TYPE_CODES = ["02", "03", "04", "05"]

FIELDS = [
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

TIME_WINDOWS = [
    {"label": "2000f2009", "start_date": "2007-10-01", "end_date": "2009-09-30", "fy_start": 2000},
    {"label": "2010f2017", "start_date": "2010-10-01", "end_date": "2017-09-30", "fy_start": 2010},
    {"label": "2018f2022", "start_date": "2018-10-01", "end_date": "2022-09-30", "fy_start": 2018},
    {"label": "2023f2025", "start_date": "2023-10-01", "end_date": "2025-09-30", "fy_start": 2023},
]

MASTER_COLUMNS = [
    "award_id", "recipient_name", "recipient_uei", "awarding_agency",
    "awarding_sub_agency", "obligated_amount", "award_date", "fiscal_year",
    "pop_state", "pop_county", "description", "source_file",
    "source_dataset", "award_category",
]

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]
PAGE_SLEEP = 0.3
RATE_LIMIT_SLEEP = 30


# ---------------------------------------------------------------------------
# Session / helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


def _derive_fiscal_year(date_str) -> str:
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
    if not filepath.exists():
        return False
    try:
        return len(pd.read_csv(filepath, dtype=str, nrows=2, low_memory=False)) > 0
    except Exception:
        return False


def _fetch_page(session: requests.Session, payload: dict, logger) -> dict | None:
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(USASPENDING_URL, json=payload, timeout=30)
            if resp.status_code == 429:
                logger.warning(f"  Rate limited — sleeping {RATE_LIMIT_SLEEP}s")
                time.sleep(RATE_LIMIT_SLEEP)
                resp = session.post(USASPENDING_URL, json=payload, timeout=30)
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code} — skipping: {resp.text[:300]}")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if 400 <= status < 500:
                logger.error(f"  HTTP {status} — skipping: {e}")
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
    all_results = []
    page = 1
    while True:
        payload = {**base_payload, "page": page}
        data = _fetch_page(session, payload, logger)
        if data is None:
            break
        results = data.get("results", [])
        if not results:
            break
        all_results.extend(results)
        if page % 10 == 0:
            logger.info(f"    Page {page} ({len(all_results)} records so far)")
        if not data.get("page_metadata", {}).get("has_next_page", False):
            break
        page += 1
        time.sleep(PAGE_SLEEP)
    return all_results


def _build_payload(filter_type: str, window: dict) -> dict:
    time_period = [{"start_date": window["start_date"], "end_date": window["end_date"]}]
    if filter_type == "pop":
        location = {"place_of_performance_locations": [{"country": "USA", "state": "PR"}]}
    else:
        location = {"recipient_locations": [{"country": "USA", "state": "PR"}]}
    return {
        "filters": {
            "award_type_codes": GRANT_TYPE_CODES,
            "agencies": [{"type": "awarding", "tier": "toptier", "name": AGENCY_NAME}],
            "time_period": time_period,
            **location,
        },
        "fields": FIELDS,
        "page": 1,
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc",
        "subawards": False,
    }


def _results_to_df(results: list[dict], source_file: str) -> pd.DataFrame:
    if not results:
        return pd.DataFrame(columns=MASTER_COLUMNS)
    df = pd.json_normalize(results)
    rename_map = {
        "Award ID": "award_id", "Recipient Name": "recipient_name",
        "recipient_uei": "recipient_uei", "Awarding Agency": "awarding_agency",
        "Awarding Sub Agency": "awarding_sub_agency", "Award Amount": "obligated_amount",
        "Start Date": "award_date", "Award Type": "award_category",
        "Place of Performance State Code": "pop_state",
        "Place of Performance County Name": "pop_county", "Description": "description",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})
    df["fiscal_year"] = df.get("award_date", pd.Series(dtype=str)).apply(_derive_fiscal_year)
    df["source_file"] = source_file
    df["source_dataset"] = "hud"
    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[MASTER_COLUMNS]


# ---------------------------------------------------------------------------
# Download + master build
# ---------------------------------------------------------------------------

def download_window(session, window, raw_dir, force, logger) -> dict:
    label = window["label"]
    stats = {"window": label, "pop_rows": 0, "recipient_rows": 0, "errors": []}
    for filter_type in ("pop", "recipient"):
        fname = f"hud_{filter_type}_{label}.csv"
        fpath = raw_dir / fname
        if not force and _file_has_data(fpath):
            rows = len(pd.read_csv(fpath, dtype=str, low_memory=False))
            logger.info(f"  Skipping {fname} (exists, {rows} rows)")
            stats[f"{filter_type}_rows"] = rows
            continue
        logger.info(f"  Fetching {fname} ({window['start_date']} → {window['end_date']}, filter={filter_type})")
        results = _paginate(session, _build_payload(filter_type, window), logger)
        if not results:
            logger.warning(f"  No results for {fname}")
            stats["errors"].append(f"{fname}: no results")
            pd.DataFrame(columns=MASTER_COLUMNS).to_csv(fpath, index=False, encoding="utf-8")
            continue
        df = _results_to_df(results, fname)
        raw_dir.mkdir(parents=True, exist_ok=True)
        df.to_csv(fpath, index=False, encoding="utf-8")
        stats[f"{filter_type}_rows"] = len(df)
        logger.info(f"  Saved {len(df)} rows → {fname}")
    return stats


def build_master(raw_dir: Path, master_path: Path, logger) -> int:
    files = sorted(raw_dir.glob("hud_*.csv"))
    if not files:
        logger.warning("  No raw HUD files found — master not written")
        return 0
    frames = []
    for f in files:
        try:
            frames.append(pd.read_csv(f, dtype=str, low_memory=False))
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
    return _run(root=root, force=False, fy_start=None)


def _run(root: Path = None, force: bool = False, fy_start: int = None) -> dict:
    if root is None:
        root = PROJECT_ROOT

    raw_dir = root / "data" / "staging" / "raw" / "hud"
    master_path = root / "data" / "staging" / "processed" / "pr_hud_master.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_hud")
    logger.info("Starting HUD grants download for Puerto Rico...")

    windows = TIME_WINDOWS
    if fy_start is not None:
        windows = [w for w in TIME_WINDOWS if w["fy_start"] >= fy_start]

    session = _session()
    all_errors = []
    total_pop = total_rec = 0
    window_stats = []

    for window in windows:
        logger.info(f"[Window {window['label']}] {window['start_date']} to {window['end_date']}")
        try:
            stats = download_window(session, window, raw_dir, force, logger)
        except Exception as e:
            logger.error(f"  Unexpected error on {window['label']}: {e}")
            stats = {"window": window["label"], "pop_rows": 0, "recipient_rows": 0, "errors": [str(e)]}
        total_pop += stats["pop_rows"]
        total_rec += stats["recipient_rows"]
        all_errors.extend(stats["errors"])
        window_stats.append(stats)
        logger.info("")

    session.close()

    logger.info("Building HUD master...")
    master_rows = build_master(raw_dir, master_path, logger)

    summary = {
        "raw_pop_rows": total_pop, "raw_recipient_rows": total_rec,
        "master_rows": master_rows, "master_path": str(master_path),
        "errors": all_errors, "windows": window_stats,
    }
    logger.info("=" * 60)
    logger.info("HUD DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  PoP rows:       {total_pop:,}")
    logger.info(f"  Recipient rows: {total_rec:,}")
    logger.info(f"  Master rows:    {master_rows:,}")
    logger.info(f"  Errors:         {len(all_errors)}")
    if all_errors:
        for err in all_errors:
            logger.warning(f"    {err}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download HUD grants for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fy-start", type=int, metavar="YEAR")
    args = parser.parse_args()
    summary = _run(force=args.force, fy_start=args.fy_start)
    print(f"\nHUD download complete.")
    print(f"  PoP rows:       {summary['raw_pop_rows']:,}")
    print(f"  Recipient rows: {summary['raw_recipient_rows']:,}")
    print(f"  Master rows:    {summary['master_rows']:,}")
    if summary["errors"]:
        for err in summary["errors"]:
            print(f"  ERROR: {err}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
