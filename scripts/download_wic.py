"""
Download USDA FNS WIC (Women, Infants, and Children) program data for Puerto Rico.

WIC is a separate FNS nutrition program (~$150M/yr in PR), distinct from NAP/SNAP.
PR WIC participants: ~100K women, infants, and children receiving food benefits.

Sources tried in order:
  1. USDA FNS WIC data portal — state-level participation/cost Excel tables
  2. data.gov CKAN search for WIC Puerto Rico
  3. USASpending fallback: CFDA 10.557 (Special Supplemental Nutrition — WIC)

Output:
  data/staging/processed/pr_wic.csv

Usage:
  python3 scripts/download_wic.py [--force]
"""

import argparse
import io
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

WIC_COLUMNS = [
    "fiscal_year", "month",
    "total_participants", "women_count", "infants_count", "children_count",
    "total_food_cost", "total_program_cost", "source_doc",
]

FNS_WIC_URLS = [
    "https://www.fns.usda.gov/pd/wic-program-data",
    "https://www.fns.usda.gov/sites/default/files/pd/26wifypart.xlsx",
    "https://www.fns.usda.gov/sites/default/files/pd/26wifycost.xlsx",
]
DATA_GOV_SEARCH = "https://catalog.data.gov/api/3/action/package_search"
USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (USDA WIC PR research)",
        "Accept": "application/json, text/html",
    })
    return s


def _get(session, url, params, logger):
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


def _fetch_fns_excel(session, logger) -> list[dict]:
    rows = []
    part_url = "https://www.fns.usda.gov/sites/default/files/pd/26wifypart.xlsx"
    cost_url = "https://www.fns.usda.gov/sites/default/files/pd/26wifycost.xlsx"

    for url, data_type in [(part_url, "participation"), (cost_url, "cost")]:
        logger.info(f"  Trying FNS WIC {data_type} Excel: {url}")
        resp = _get(session, url, {}, logger)
        if not resp or not resp.content:
            continue
        try:
            xl = pd.ExcelFile(io.BytesIO(resp.content))
            for sheet in xl.sheet_names:
                try:
                    df = xl.parse(sheet, dtype=str)
                except Exception:
                    continue
                # Look for Puerto Rico row
                for col in df.columns:
                    col_str = str(col).lower()
                    if "state" in col_str or col_str in ("0", "unnamed: 0"):
                        pr_mask = df[col].str.upper().str.contains("PUERTO RICO|PR", na=False)
                        df_pr = df[pr_mask]
                        if df_pr.empty:
                            continue
                        for _, r in df_pr.iterrows():
                            row_dict = r.to_dict()
                            if data_type == "participation":
                                rows.append({
                                    "fiscal_year": str(sheet),
                                    "month": "",
                                    "total_participants": str(row_dict.get("Total", row_dict.get("TOTAL", ""))),
                                    "women_count": str(row_dict.get("Women", row_dict.get("WOMEN", ""))),
                                    "infants_count": str(row_dict.get("Infants", row_dict.get("INFANTS", ""))),
                                    "children_count": str(row_dict.get("Children", row_dict.get("CHILDREN", ""))),
                                    "total_food_cost": "",
                                    "total_program_cost": "",
                                    "source_doc": url,
                                })
                            else:
                                if rows:
                                    # Merge cost into existing participation row
                                    for existing_row in rows:
                                        if existing_row.get("fiscal_year") == str(sheet):
                                            existing_row["total_food_cost"] = str(
                                                row_dict.get("Food Cost", row_dict.get("FOOD COST", ""))
                                            )
                                            existing_row["total_program_cost"] = str(
                                                row_dict.get("Total Cost", row_dict.get("TOTAL COST", ""))
                                            )
                                else:
                                    rows.append({
                                        "fiscal_year": str(sheet),
                                        "month": "",
                                        "total_participants": "",
                                        "women_count": "",
                                        "infants_count": "",
                                        "children_count": "",
                                        "total_food_cost": str(row_dict.get("Food Cost", "")),
                                        "total_program_cost": str(row_dict.get("Total Cost", "")),
                                        "source_doc": url,
                                    })
        except Exception as e:
            logger.warning(f"  Could not parse FNS WIC Excel {url}: {e}")
    if rows:
        logger.info(f"  FNS WIC Excel: {len(rows)} rows")
    return rows


def _fetch_data_gov(session, logger) -> list[dict]:
    rows = []
    logger.info("  Searching data.gov for WIC Puerto Rico datasets...")
    params = {"q": "WIC women infants children Puerto Rico nutrition", "rows": 10}
    resp = _get(session, DATA_GOV_SEARCH, params, logger)
    if not resp:
        return rows
    try:
        result = resp.json()
    except Exception:
        return rows
    for pkg in result.get("result", {}).get("results", []):
        for resource in pkg.get("resources", []):
            url = resource.get("url", "")
            if not url or resource.get("format", "").upper() not in ("CSV", "JSON", "XLSX", "XLS"):
                continue
            resp2 = _get(session, url, {}, logger)
            if not resp2 or not resp2.content:
                continue
            try:
                if url.lower().endswith((".xlsx", ".xls")):
                    df = pd.read_excel(io.BytesIO(resp2.content), dtype=str)
                elif url.lower().endswith(".csv"):
                    df = pd.read_csv(io.BytesIO(resp2.content), dtype=str, low_memory=False)
                else:
                    df = pd.json_normalize(resp2.json() if isinstance(resp2.json(), list) else [])
                state_cols = [c for c in df.columns if "state" in c.lower()]
                if state_cols:
                    df = df[df[state_cols[0]].str.upper().str.contains("PUERTO RICO|PR", na=False)]
                if df.empty:
                    continue
                for _, r in df.iterrows():
                    rd = r.to_dict()
                    rows.append({
                        "fiscal_year": str(rd.get("fiscal_year", rd.get("year", ""))),
                        "month": str(rd.get("month", "")),
                        "total_participants": str(rd.get("total_participants", rd.get("total", ""))),
                        "women_count": str(rd.get("women", rd.get("women_count", ""))),
                        "infants_count": str(rd.get("infants", rd.get("infants_count", ""))),
                        "children_count": str(rd.get("children", rd.get("children_count", ""))),
                        "total_food_cost": str(rd.get("food_cost", rd.get("total_food_cost", ""))),
                        "total_program_cost": str(rd.get("program_cost", rd.get("total_cost", ""))),
                        "source_doc": url,
                    })
                if rows:
                    logger.info(f"  data.gov WIC: {len(rows)} PR rows")
                    return rows
            except Exception as e:
                logger.warning(f"  Could not parse {url[:60]}: {e}")
    return rows


def _fetch_usaspending(session, logger) -> list[dict]:
    rows = []
    logger.info("  Trying USASpending fallback for WIC (CFDA 10.557)...")
    payload = {
        "filters": {
            "program_numbers": ["10.557"],
            "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
        },
        "fields": [
            "Award ID", "Recipient Name", "recipient_uei", "Awarding Agency",
            "Awarding Sub Agency", "Award Amount", "Start Date", "Award Type",
            "Place of Performance State Code", "Description",
        ],
        "page": 1, "limit": 100, "sort": "Award Amount", "order": "desc", "subawards": False,
    }
    page = 1
    while True:
        payload["page"] = page
        try:
            resp = session.post(USASPENDING_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning(f"  USASpending error: {e}")
            break
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            rows.append({
                "fiscal_year": str(r.get("Start Date", ""))[:4] if r.get("Start Date") else "",
                "month": "",
                "total_participants": "",
                "women_count": "",
                "infants_count": "",
                "children_count": "",
                "total_food_cost": "",
                "total_program_cost": str(r.get("Award Amount", "")),
                "source_doc": "usaspending_cfda_10.557",
            })
        if not data.get("page_metadata", {}).get("has_next_page", False):
            break
        page += 1
        time.sleep(0.3)
    if rows:
        logger.info(f"  USASpending WIC: {len(rows)} rows")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_wic.csv"

    logger = setup_logging("download_wic")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    fns_rows = _fetch_fns_excel(session, logger)
    all_rows.extend(fns_rows)

    if not all_rows:
        dg_rows = _fetch_data_gov(session, logger)
        all_rows.extend(dg_rows)

    if not all_rows:
        usa_rows = _fetch_usaspending(session, logger)
        all_rows.extend(usa_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No WIC data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://www.fns.usda.gov/pd/wic-program-data"
        )
        pd.DataFrame(columns=WIC_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in WIC_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[WIC_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download USDA WIC program data for Puerto Rico")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nWIC: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
