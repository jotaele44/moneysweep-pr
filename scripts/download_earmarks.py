"""
Download congressional earmarks for Puerto Rico from USASpending.

Earmarks (congressionally directed spending) resumed in FY2022. PR delegation
earmarks appear in appropriations bills across all agencies. This script uses
the USASpending disaster emergency fund code filter plus keyword matching on
award descriptions to identify earmarked awards.

Source: USASpending API (spending_by_award) — no auth required

Output:
  data/staging/processed/pr_earmarks.csv

Usage:
  python3 scripts/download_earmarks.py
  python3 scripts/download_earmarks.py --force
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

# Earmarks appear across all award types FY2022+
AWARD_TYPE_CODES = ["02", "03", "04", "05", "A", "B", "C", "D"]

FIELDS = [
    "Award ID", "Recipient Name", "recipient_uei",
    "Awarding Agency", "Awarding Sub Agency", "Award Amount",
    "Start Date", "Award Type",
    "Place of Performance State Code", "Place of Performance County Name", "Description",
]

# Earmark keyword search — USASpending description field often includes "congressionally directed"
EARMARK_KEYWORDS = [
    "congressionally directed",
    "congressional earmark",
    "directed spending",
    "community project funding",  # House term post-2022
    "spending direction",
]

TIME_WINDOWS = [
    {"label": "2022f2026", "start_date": "2022-10-01", "end_date": "2026-09-30"},
]

EARMARK_COLUMNS = [
    "award_id", "recipient_name", "recipient_uei", "awarding_agency",
    "awarding_sub_agency", "obligated_amount", "award_date", "fiscal_year",
    "pop_state", "pop_county", "description", "source_file",
    "source_dataset", "award_category", "earmark_keyword_matched",
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
                logger.error(f"  HTTP {resp.status_code}: {resp.text[:200]}")
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
            time.sleep(RETRY_BACKOFF[attempt])
    logger.error(f"  All attempts failed: {last_err}")
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


def _build_payload(window):
    return {
        "filters": {
            "award_type_codes": AWARD_TYPE_CODES,
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
            "time_period": [{"start_date": window["start_date"], "end_date": window["end_date"]}],
            # Filter for congressionally directed spending flag
            "def_codes": ["L", "M", "N", "O", "P", "Q"],  # IRA/IIJA DEF codes include directed spending
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
        return pd.DataFrame(columns=EARMARK_COLUMNS)
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
    df["source_dataset"] = "earmarks"

    # Flag which keyword matched
    def _kw_match(desc):
        if not desc or pd.isna(desc):
            return ""
        desc_lower = str(desc).lower()
        for kw in EARMARK_KEYWORDS:
            if kw in desc_lower:
                return kw
        return ""

    df["earmark_keyword_matched"] = df.get("description", pd.Series(dtype=str)).apply(_kw_match)

    for col in EARMARK_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[EARMARK_COLUMNS]


def run(root=None):
    return _run(root=root, force=False)


def _run(root=None, force=False):
    if root is None:
        root = PROJECT_ROOT
    out_path = root / "data" / "staging" / "processed" / "pr_earmarks.csv"
    logger = setup_logging("download_earmarks")
    logger.info("Starting congressional earmarks download for Puerto Rico...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_earmarks.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    session = _session()
    all_frames = []
    errors = []

    for window in TIME_WINDOWS:
        logger.info(f"  Window: {window['start_date']} → {window['end_date']}")
        fname = f"earmarks_{window['label']}.csv"
        results = _paginate(session, _build_payload(window), logger)
        if not results:
            logger.warning(f"  No earmark results for {window['label']}")
            errors.append(f"{fname}: no results")
            continue
        df = _results_to_df(results, fname)
        all_frames.append(df)
        logger.info(f"  {len(df)} earmark records for {window['label']}")

    session.close()

    if all_frames:
        combined = pd.concat(all_frames, ignore_index=True)
        if "award_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["award_id"], keep="first")
    else:
        combined = pd.DataFrame(columns=EARMARK_COLUMNS)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(out_path, index=False, encoding="utf-8")

    total_amt = pd.to_numeric(combined.get("obligated_amount", pd.Series()), errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("EARMARKS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total earmark records: {len(combined):,}")
    logger.info(f"  Total obligated:       ${total_amt:,.0f}")

    return {"rows": len(combined), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Download congressional earmarks for Puerto Rico")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nEarmarks complete: {result['rows']:,} records")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
