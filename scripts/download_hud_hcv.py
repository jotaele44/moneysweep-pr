"""
Download HUD Section 8 / Housing Choice Voucher (HCV) data for Puerto Rico.

HUD HCV is the largest housing subsidy flow to PR (~$500M-1B/yr).
Different from HUD-CPD CDBG/formula grants (covered by download_hud.py).

Sources tried in order:
  1. HUD Picture of Subsidized Households — annual CSV by state (PR)
  2. HUD Open Data Socrata — HCV datasets filtered to PR
  3. USASpending fallback: CFDA 14.871 (HCV) + PR filter

Output:
  data/staging/processed/pr_hud_hcv.csv

Usage:
  python3 scripts/download_hud_hcv.py [--force]
"""

import argparse
import io
import re
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

HCV_COLUMNS = [
    "year", "program", "total_units", "people_per_unit",
    "total_households", "pct_minority", "avg_annual_income",
    "avg_rent_burden", "total_annual_cost", "source_doc",
]

HUD_USER_BASE = "https://www.huduser.gov/portal/datasets/assthsg.html"
HUD_SOCRATA_ENDPOINTS = [
    "https://hudgis-hud.opendata.arcgis.com/datasets",
    "https://data.hud.gov/resource/wazz-bx2e.json",
    "https://data.hud.gov/resource/5j9k-c4hy.json",
]
HUD_PIC_BASE = "https://www.huduser.gov/portal/datasets/assthsg/StateSummary_2"
USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (HUD HCV PR research)",
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


def _fetch_hud_pic(session, logger) -> list[dict]:
    rows = []
    current_year = 2024
    for year in range(current_year, 2018, -1):
        url = f"{HUD_PIC_BASE}{year}.xlsx"
        logger.info(f"  Trying HUD PIC {year}: {url}")
        resp = _get(session, url, {}, logger)
        if not resp or not resp.content:
            url_csv = f"https://www.huduser.gov/portal/datasets/assthsg/StateSummary_{year}.csv"
            resp = _get(session, url_csv, {}, logger)
        if not resp or not resp.content:
            continue
        try:
            if url.endswith(".xlsx") or (resp and "excel" in resp.headers.get("content-type", "")):
                df = pd.read_excel(io.BytesIO(resp.content), dtype=str)
            else:
                df = pd.read_csv(io.BytesIO(resp.content), dtype=str, low_memory=False)
        except Exception as e:
            logger.warning(f"  Could not parse HUD PIC {year}: {e}")
            continue

        state_cols = [c for c in df.columns if "state" in c.lower() or c.upper() in ("ST", "STATE_CD")]
        if not state_cols:
            continue
        pr_mask = df[state_cols[0]].str.upper().str.contains("PR|PUERTO RICO|72", na=False)
        df_pr = df[pr_mask].copy()
        if df_pr.empty:
            continue

        for _, r in df_pr.iterrows():
            rd = r.to_dict()
            program = str(rd.get("Program", rd.get("program", rd.get("PROGRAM", "HCV"))))
            if not any(kw in program.upper() for kw in ["VOUCHER", "HCV", "SECTION 8", "HOUSING"]):
                continue
            rows.append({
                "year": str(year),
                "program": program,
                "total_units": str(rd.get("Units Available", rd.get("total_units", rd.get("UNITS", "")))),
                "people_per_unit": str(rd.get("People Per Unit", rd.get("persons_per_unit", ""))),
                "total_households": str(rd.get("Total Households", rd.get("households", ""))),
                "pct_minority": str(rd.get("Percent Minority", rd.get("pct_minority", ""))),
                "avg_annual_income": str(rd.get("Average Annual Income", rd.get("avg_income", ""))),
                "avg_rent_burden": str(rd.get("Average Rent Burden", rd.get("avg_rent_burden", ""))),
                "total_annual_cost": str(rd.get("Total Annual Cost", rd.get("total_cost", ""))),
                "source_doc": url,
            })
        if rows:
            logger.info(f"  HUD PIC {year}: {len(rows)} PR HCV rows")
            return rows
    return rows


def _fetch_hud_socrata(session, logger) -> list[dict]:
    rows = []
    endpoints = [
        "https://data.hud.gov/resource/wazz-bx2e.json",
        "https://data.hud.gov/resource/5j9k-c4hy.json",
        "https://data.hud.gov/resource/52qi-re87.json",
    ]
    for endpoint in endpoints:
        logger.info(f"  Trying HUD Socrata: {endpoint}")
        params = {"$where": "state='PR' OR state_code='72' OR state_name='Puerto Rico'", "$limit": 5000}
        resp = _get(session, endpoint, params, logger)
        if not resp:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        if not data or not isinstance(data, list):
            continue
        for r in data:
            program = str(r.get("program", r.get("program_type", "HCV")))
            rows.append({
                "year": str(r.get("year", r.get("report_year", ""))),
                "program": program,
                "total_units": str(r.get("total_units", r.get("units_available", ""))),
                "people_per_unit": str(r.get("people_per_unit", r.get("persons_per_unit", ""))),
                "total_households": str(r.get("total_households", r.get("households", ""))),
                "pct_minority": str(r.get("pct_minority", r.get("percent_minority", ""))),
                "avg_annual_income": str(r.get("avg_annual_income", r.get("average_income", ""))),
                "avg_rent_burden": str(r.get("avg_rent_burden", r.get("rent_burden", ""))),
                "total_annual_cost": str(r.get("total_annual_cost", r.get("total_cost", ""))),
                "source_doc": endpoint,
            })
        if rows:
            logger.info(f"  HUD Socrata: {len(rows)} rows")
            return rows
    return rows


def _fetch_usaspending(session, logger) -> list[dict]:
    rows = []
    logger.info("  Trying USASpending fallback for HCV (CFDA 14.871)...")
    payload = {
        "filters": {
            "program_numbers": ["14.871"],
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
            logger.warning(f"  USASpending HCV error: {e}")
            break
        results = data.get("results", [])
        if not results:
            break
        for r in results:
            rows.append({
                "year": str(r.get("Start Date", ""))[:4],
                "program": "HCV",
                "total_units": "",
                "people_per_unit": "",
                "total_households": "",
                "pct_minority": "",
                "avg_annual_income": "",
                "avg_rent_burden": "",
                "total_annual_cost": str(r.get("Award Amount", "")),
                "source_doc": "usaspending_cfda_14.871",
            })
        if not data.get("page_metadata", {}).get("has_next_page", False):
            break
        page += 1
        time.sleep(0.3)
    if rows:
        logger.info(f"  USASpending HCV: {len(rows)} rows")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_hud_hcv.csv"

    logger = setup_logging("download_hud_hcv")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    pic_rows = _fetch_hud_pic(session, logger)
    all_rows.extend(pic_rows)

    if not all_rows:
        socrata_rows = _fetch_hud_socrata(session, logger)
        all_rows.extend(socrata_rows)

    if not all_rows:
        usa_rows = _fetch_usaspending(session, logger)
        all_rows.extend(usa_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No HUD HCV data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://www.huduser.gov/portal/datasets/assthsg.html"
        )
        pd.DataFrame(columns=HCV_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in HCV_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[HCV_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download HUD HCV Section 8 voucher data for PR")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHUD HCV: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
