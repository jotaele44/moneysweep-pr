"""
Download NIH (National Institutes of Health) research grants to Puerto Rico.

PR institutions (UPR system, Recinto de Ciencias Médicas, Ponce School of Medicine,
Ana G. Méndez University) receive significant NIH funding. Uses the NIH Reporter
API for richer metadata (PI names, abstracts, study sections) than USASpending
provides for NIH awards.

Sources tried in order:
  1. NIH Reporter API v2 (reporter.nih.gov) — free, no auth, returns full project data
  2. USASpending fallback — HHS subtier "National Institutes of Health" with PR filter

Output:
  data/staging/processed/pr_nih_grants.csv

Usage:
  python3 scripts/download_nih.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

NIH_REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

NIH_COLUMNS = [
    "fiscal_year", "project_num", "project_title",
    "org_name", "org_normalized", "pi_names",
    "activity_code", "award_amount", "total_cost",
    "start_date", "end_date", "study_section",
    "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR NIH research grant mapping)",
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
                logger.warning(f"  HTTP {resp.status_code}: {resp.text[:200]}")
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


def _normalize_name(name: str) -> str:
    import re
    if not name:
        return ""
    n = re.sub(r"[^\w\s]", " ", name.upper())
    n = re.sub(r"\s+", " ", n).strip()
    suffixes = {"INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "THE", "OF", "UNIVERSITY", "UNIV"}
    tokens = n.split()
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _fetch_nih_reporter(session: requests.Session, logger) -> list[dict]:
    rows = []
    offset = 0
    limit = 500
    logger.info("  Querying NIH Reporter API for PR organizations...")
    while True:
        payload = {
            "criteria": {
                "org_state": "PR",
                "fiscal_years": list(range(2010, 2026)),
            },
            "include_fields": [
                "ProjectNum", "ProjectTitle", "OrgName", "ContactPiName",
                "FiscalYear", "AwardAmount", "TotalCost",
                "ProjectStartDate", "ProjectEndDate",
                "ActivityCode", "StudySection",
            ],
            "offset": offset,
            "limit": limit,
            "sort_field": "TotalCost",
            "sort_order": "desc",
        }
        data = _post(session, NIH_REPORTER_URL, payload, logger)
        if not data:
            break
        results = data.get("results", [])
        if not results:
            break
        rows.extend(results)
        total = data.get("meta", {}).get("total", 0)
        logger.info(f"  NIH Reporter: offset {offset}, got {len(results)} (total={total:,})")
        if offset + limit >= total:
            break
        offset += limit
    return rows


def _fetch_usaspending_nih(session: requests.Session, logger) -> list[dict]:
    rows = []
    page = 1
    logger.info("  Querying USASpending for NIH grants in PR (fallback)...")
    while True:
        payload = {
            "filters": {
                "award_type_codes": ["02", "03", "04", "05"],
                "agencies": [
                    {"type": "awarding", "tier": "toptier", "name": "Department of Health and Human Services"},
                    {"type": "awarding", "tier": "subtier", "name": "National Institutes of Health"},
                ],
                "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
            },
            "fields": [
                "Award ID", "Recipient Name", "Award Amount",
                "Awarding Sub Agency", "Start Date", "Description",
            ],
            "page": page,
            "limit": 100,
            "sort": "Award Amount",
            "order": "desc",
            "subawards": False,
        }
        data = _post(session, USASPENDING_URL, payload, logger)
        if not data:
            break
        results = data.get("results", [])
        if not results:
            break
        rows.extend(results)
        if not data.get("page_metadata", {}).get("has_next_page", False):
            break
        page += 1
        time.sleep(PAGE_SLEEP)
    return rows


def _normalize_reporter_records(records: list[dict], logger) -> list[dict]:
    rows = []
    for r in records:
        pi_list = r.get("ContactPiName", "") or ""
        rows.append({
            "fiscal_year": str(r.get("FiscalYear", "")),
            "project_num": str(r.get("ProjectNum", "")),
            "project_title": str(r.get("ProjectTitle", "")),
            "org_name": str(r.get("OrgName", "")),
            "org_normalized": _normalize_name(str(r.get("OrgName", ""))),
            "pi_names": str(pi_list),
            "activity_code": str(r.get("ActivityCode", "")),
            "award_amount": str(r.get("AwardAmount", "")),
            "total_cost": str(r.get("TotalCost", "")),
            "start_date": str(r.get("ProjectStartDate", "")),
            "end_date": str(r.get("ProjectEndDate", "")),
            "study_section": str(r.get("StudySection", "")),
            "source_doc": "nih_reporter_api",
        })
    return rows


def _normalize_usaspending_records(records: list[dict], logger) -> list[dict]:
    rows = []
    for r in records:
        award_date = str(r.get("Start Date", ""))
        fy = ""
        try:
            d = pd.to_datetime(award_date, errors="coerce")
            if not pd.isna(d):
                fy = str(d.year + 1) if d.month >= 10 else str(d.year)
        except Exception:
            pass
        org = str(r.get("Recipient Name", ""))
        rows.append({
            "fiscal_year": fy,
            "project_num": str(r.get("Award ID", "")),
            "project_title": str(r.get("Description", "")),
            "org_name": org,
            "org_normalized": _normalize_name(org),
            "pi_names": "",
            "activity_code": "",
            "award_amount": str(r.get("Award Amount", "")),
            "total_cost": "",
            "start_date": award_date,
            "end_date": "",
            "study_section": "",
            "source_doc": "usaspending_nih",
        })
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_nih_grants.csv"

    logger = setup_logging("download_nih")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    reporter_records = _fetch_nih_reporter(session, logger)
    if reporter_records:
        logger.info(f"  NIH Reporter: {len(reporter_records):,} records")
        all_rows.extend(_normalize_reporter_records(reporter_records, logger))
    else:
        logger.info("  NIH Reporter returned no data — trying USASpending fallback...")
        usa_records = _fetch_usaspending_nih(session, logger)
        if usa_records:
            logger.info(f"  USASpending NIH: {len(usa_records):,} records")
            all_rows.extend(_normalize_usaspending_records(usa_records, logger))

    session.close()

    if not all_rows:
        logger.warning(
            "  No NIH grant data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://reporter.nih.gov/search-results"
        )
        pd.DataFrame(columns=NIH_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in NIH_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[NIH_COLUMNS]
    df = df.drop_duplicates(subset=["project_num"], keep="first")
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download NIH research grants for Puerto Rico")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nNIH grants: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
