"""
Download Ex-Im Bank (Export-Import Bank) loans and guarantees for Puerto Rico.

Ex-Im supports PR-based exporters and foreign buyers of PR goods. Loan/guarantee
recipients overlap with the broader federal contractor network.

Output:
  data/staging/raw/exim/exim_pop_<label>.csv
  data/staging/raw/exim/exim_recipient_<label>.csv
  data/staging/processed/pr_exim_master.csv

Usage:
  python3 scripts/download_exim.py
  python3 scripts/download_exim.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

AGENCY_NAME = "Export-Import Bank of the United States"
GRANT_TYPE_CODES = ["07", "08"]   # direct loans + guaranteed loans

FIELDS = [
    "Award ID", "Recipient Name", "recipient_uei",
    "Awarding Agency", "Awarding Sub Agency", "Award Amount",
    "Start Date", "Award Type",
    "Place of Performance State Code", "Place of Performance County Name", "Description",
]

TIME_WINDOWS = [
    {"label": "2000f2009", "start_date": "2007-10-01", "end_date": "2009-09-30", "fy_start": 2000},
    {"label": "2010f2017", "start_date": "2010-10-01", "end_date": "2017-09-30", "fy_start": 2010},
    {"label": "2018f2022", "start_date": "2018-10-01", "end_date": "2022-09-30", "fy_start": 2018},
    {"label": "2023f2026", "start_date": "2023-10-01", "end_date": "2026-09-30", "fy_start": 2023},
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


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


def _derive_fiscal_year(date_str):
    if not date_str or pd.isna(date_str):
        return ""
    try:
        d = pd.to_datetime(str(date_str), errors="coerce")
        if pd.isna(d):
            return ""
        return str(d.year + 1) if d.month >= 10 else str(d.year)
    except Exception:
        return ""


def _file_has_data(filepath):
    if not filepath.exists():
        return False
    try:
        return len(pd.read_csv(filepath, dtype=str, nrows=2, low_memory=False)) > 0
    except Exception:
        return False


def _fetch_page(session, payload, logger):
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


def _paginate(session, base_payload, logger):
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
        if not data.get("page_metadata", {}).get("has_next_page", False):
            break
        page += 1
        time.sleep(PAGE_SLEEP)
    return all_results


def _build_payload(filter_type, window):
    time_period = [{"start_date": window["start_date"], "end_date": window["end_date"]}]
    location = (
        {"place_of_performance_locations": [{"country": "USA", "state": "PR"}]}
        if filter_type == "pop"
        else {"recipient_locations": [{"country": "USA", "state": "PR"}]}
    )
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


def _results_to_df(results, source_file):
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
    df["source_dataset"] = "exim"
    for col in MASTER_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[MASTER_COLUMNS]


def build_master(raw_dir, master_path, logger):
    files = sorted(raw_dir.glob("exim_*.csv"))
    if not files:
        logger.warning("  No raw Ex-Im files found — master not written")
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
    if "award_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["award_id"], keep="first")
    master_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(combined):,} rows → {master_path.name}")
    return len(combined)


def run(root=None):
    return _run(root=root, force=False, fy_start=None)


def _run(root=None, force=False, fy_start=None):
    if root is None:
        root = PROJECT_ROOT
    raw_dir = root / "data" / "staging" / "raw" / "exim"
    master_path = root / "data" / "staging" / "processed" / "pr_exim_master.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_exim")
    logger.info("Starting Ex-Im Bank download for Puerto Rico...")
    windows = TIME_WINDOWS
    if fy_start is not None:
        windows = [w for w in TIME_WINDOWS if w["fy_start"] >= fy_start]
    session = _session()
    all_errors = []
    total_pop = total_rec = 0
    for window in windows:
        logger.info(f"[Window {window['label']}]")
        for filter_type in ("pop", "recipient"):
            fname = f"exim_{filter_type}_{window['label']}.csv"
            fpath = raw_dir / fname
            if not force and _file_has_data(fpath):
                rows = len(pd.read_csv(fpath, dtype=str, low_memory=False))
                logger.info(f"  Skipping {fname} ({rows} rows)")
                if filter_type == "pop":
                    total_pop += rows
                else:
                    total_rec += rows
                continue
            results = _paginate(session, _build_payload(filter_type, window), logger)
            if not results:
                all_errors.append(f"{fname}: no results")
                pd.DataFrame(columns=MASTER_COLUMNS).to_csv(fpath, index=False, encoding="utf-8")
                continue
            df = _results_to_df(results, fname)
            df.to_csv(fpath, index=False, encoding="utf-8")
            if filter_type == "pop":
                total_pop += len(df)
            else:
                total_rec += len(df)
            logger.info(f"  Saved {len(df)} rows → {fname}")
    session.close()
    master_rows = build_master(raw_dir, master_path, logger)
    logger.info("=" * 60)
    logger.info("EX-IM DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  PoP rows:    {total_pop:,}")
    logger.info(f"  Recip rows:  {total_rec:,}")
    logger.info(f"  Master rows: {master_rows:,}")
    return {"raw_pop_rows": total_pop, "raw_recipient_rows": total_rec,
            "master_rows": master_rows, "errors": all_errors}


def main():
    parser = argparse.ArgumentParser(description="Download Ex-Im Bank data for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--fy-start", type=int, metavar="YEAR")
    args = parser.parse_args()
    summary = _run(force=args.force, fy_start=args.fy_start)
    print(f"\nEx-Im download complete: {summary['master_rows']:,} master rows")
    return 1 if summary["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
