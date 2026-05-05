"""
Download Veterans Affairs (VA) benefit payments and contract spending for Puerto Rico.

PR has ~90,000 veterans receiving ~$500-600M/year in compensation, pension,
education, and healthcare benefits. The San Juan VA Medical Center (VAMC) is
one of the largest federal healthcare facilities on the island.

Sources tried in order:
  1. USASpending API — VA contracts and grants with PR place of performance
  2. VA Open Data (data.va.gov) — vetdata expenditure tables
  3. VA National Center for Veterans Analysis and Statistics Excel files

Outputs:
  data/staging/processed/pr_va_benefits.csv

Usage:
  python3 scripts/download_va.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

USASPENDING_SEARCH = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
USASPENDING_DOWNLOAD = "https://api.usaspending.gov/api/v2/bulk_download/awards/"
VA_OPEN_DATA_BASE = "https://www.data.va.gov"
VA_VETDATA_BASE = "https://www.va.gov/vetdata"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]
PAGE_SIZE = 100

VA_COLUMNS = [
    "fiscal_year",
    "benefit_type",
    "recipient_name",
    "recipient_normalized",
    "recipient_count",
    "total_expenditure",
    "avg_benefit",
    "facility_name",
    "contract_id",
    "obligation_date",
    "source_system",
    "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR VA benefits research)",
        "Accept": "application/json",
        "Content-Type": "application/json",
    })
    return s


def _post(session: requests.Session, url: str, payload: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} — body: {resp.text[:300]}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  Request failed: {exc}")
    return None


def _fetch_usaspending_va(session: requests.Session, logger) -> list[dict]:
    """Fetch VA contracts and grants for PR from USASpending API."""
    rows = []
    page = 1

    logger.info("  Querying USASpending for VA awards with PR place of performance...")
    while True:
        payload = {
            "filters": {
                "agencies": [{"type": "awarding", "tier": "toptier", "name": "Department of Veterans Affairs"}],
                "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
            },
            "fields": [
                "Award ID", "Recipient Name", "Award Amount", "Awarding Agency",
                "Awarding Sub Agency", "Award Date", "Award Type", "Description",
                "Place of Performance State Code",
            ],
            "page": page,
            "limit": PAGE_SIZE,
            "sort": "Award Amount",
            "order": "desc",
        }
        data = _post(session, USASPENDING_SEARCH, payload, logger)
        if not data:
            break

        results = data.get("results", [])
        if not results:
            break

        rows.extend(results)
        logger.info(f"  USASpending VA: page {page}, {len(rows):,} records so far")

        total = data.get("page_metadata", {}).get("total", 0)
        if page * PAGE_SIZE >= total or not data.get("page_metadata", {}).get("hasNext", False):
            break
        page += 1

    return rows


def _fetch_va_open_data(session: requests.Session, logger) -> list[dict]:
    """Query data.va.gov CKAN API for PR-related datasets."""
    rows = []
    try:
        search_url = f"{VA_OPEN_DATA_BASE}/api/views"
        data = _get(session, search_url, {"limit": 50}, logger)
        if not data:
            return rows

        items = data if isinstance(data, list) else []
        for view in items[:10]:
            view_id = view.get("id", "")
            if not view_id:
                continue
            data_url = f"{VA_OPEN_DATA_BASE}/api/views/{view_id}/rows.json"
            vdata = _get(session, data_url, {}, logger)
            if not vdata:
                continue
            cols = [c.get("fieldName", "") for c in vdata.get("meta", {}).get("view", {}).get("columns", [])]
            for r in vdata.get("data", []):
                row_dict = dict(zip(cols, r))
                state_val = str(row_dict.get("state", row_dict.get("state_name", ""))).upper()
                if state_val in ("PR", "PUERTO RICO"):
                    rows.append(row_dict)
            if rows:
                logger.info(f"  VA Open Data {view_id}: {len(rows)} PR rows")
    except Exception as e:
        logger.warning(f"  VA Open Data failed: {e}")
    return rows


def _normalize_records(records: list[dict], source_system: str, logger) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=VA_COLUMNS)

    df = pd.json_normalize(records)

    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_").replace("-", "_")
        if ("fiscal_year" in cl or "fy" == cl) and "fiscal_year" not in rename.values():
            rename[col] = "fiscal_year"
        elif "benefit_type" in cl and "benefit_type" not in rename.values():
            rename[col] = "benefit_type"
        elif ("recipient" in cl or "vendor" in cl or "awardee" in cl) and "name" in cl and "recipient_name" not in rename.values():
            rename[col] = "recipient_name"
        elif "count" in cl and "recipient" in cl and "recipient_count" not in rename.values():
            rename[col] = "recipient_count"
        elif ("amount" in cl or "expenditure" in cl or "obligation" in cl) and "total_expenditure" not in rename.values():
            rename[col] = "total_expenditure"
        elif "avg" in cl and "benefit" in cl:
            rename[col] = "avg_benefit"
        elif "facility" in cl and "name" in cl:
            rename[col] = "facility_name"
        elif ("award_id" in cl or "contract_id" in cl or "piid" in cl) and "contract_id" not in rename.values():
            rename[col] = "contract_id"
        elif ("award_date" in cl or "obligation_date" in cl) and "obligation_date" not in rename.values():
            rename[col] = "obligation_date"

    df = df.rename(columns=rename)
    df["source_system"] = source_system
    df["source_doc"] = source_system

    if "recipient_name" in df.columns:
        df["recipient_normalized"] = df["recipient_name"].apply(
            lambda x: _normalize_name(str(x or ""))
        )
    else:
        df["recipient_normalized"] = ""

    for col in VA_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[VA_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_va_benefits.csv"

    logger = setup_logging("download_va")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    frames: list[pd.DataFrame] = []

    logger.info("  Fetching VA contracts from USASpending API...")
    usa_records = _fetch_usaspending_va(session, logger)
    if usa_records:
        df_usa = _normalize_records(usa_records, "usaspending_va", logger)
        frames.append(df_usa)
        logger.info(f"  USASpending VA: {len(df_usa):,} records")

    if not frames:
        logger.info("  Trying VA Open Data portal...")
        va_records = _fetch_va_open_data(session, logger)
        if va_records:
            df_va = _normalize_records(va_records, "va_open_data", logger)
            frames.append(df_va)
            logger.info(f"  VA Open Data: {len(df_va):,} records")

    session.close()

    if not frames:
        logger.warning(
            "  No VA data retrieved. Writing empty schema.\n"
            "  Manual alternative: download from\n"
            f"  {VA_VETDATA_BASE}/expenditures.asp"
        )
        pd.DataFrame(columns=VA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.concat(frames, ignore_index=True)
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")

    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR VA benefit and contract data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nVA benefits: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
