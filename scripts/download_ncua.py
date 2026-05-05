"""
Download NCUA credit union call report data for Puerto Rico.

PR has a large credit union sector ($4-6B in assets, ~1M members).
NCUA publishes quarterly call reports with no auth required.
Complements FDIC bank data (download_fdic.py).

Sources tried in order:
  1. NCUA call report bulk CSV downloads by state (quarterly)
  2. NCUA credit union search API — filter by state=PR

Output:
  data/staging/processed/pr_ncua_credit_unions.csv

Usage:
  python3 scripts/download_ncua.py [--force]
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

NCUA_COLUMNS = [
    "reporting_period", "cu_number", "cu_name", "cu_normalized",
    "total_assets", "total_shares", "total_loans", "net_worth",
    "members_count", "city", "state", "source_doc",
]

NCUA_CALL_REPORT_BASE = "https://www.ncua.gov/files/publications/analysis"
NCUA_SEARCH_API = "https://www.mycreditunion.gov/api/CreditUnionData/CreditUnionList"
NCUA_DATA_DOWNLOAD = "https://www.ncua.gov/analysis/credit-union-corporate-call-report-data/call-report-data-download"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (NCUA credit union PR research)",
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


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    n = re.sub(r"[^\w\s]", " ", str(name).upper())
    n = re.sub(r"\s+", " ", n).strip()
    suffixes = {"FCU", "CU", "FEDERAL", "CREDIT", "UNION", "COOPERATIVE", "COOP", "INC"}
    tokens = n.split()
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _fetch_ncua_search_api(session, logger) -> list[dict]:
    rows = []
    logger.info("  Querying NCUA credit union search API for PR...")
    params = {"state": "PR", "pageSize": 1000, "pageNumber": 1}
    resp = _get(session, NCUA_SEARCH_API, params, logger)
    if not resp:
        return rows
    try:
        data = resp.json()
    except Exception:
        return rows

    cu_list = data if isinstance(data, list) else data.get("creditUnions", data.get("data", []))
    for cu in cu_list:
        name = str(cu.get("CreditUnionName", cu.get("name", cu.get("cu_name", ""))))
        rows.append({
            "reporting_period": str(cu.get("reportingPeriod", cu.get("quarter", ""))),
            "cu_number": str(cu.get("CUNumber", cu.get("cu_number", cu.get("charterNumber", "")))),
            "cu_name": name,
            "cu_normalized": _normalize_name(name),
            "total_assets": str(cu.get("TotalAssets", cu.get("total_assets", cu.get("assets", "")))),
            "total_shares": str(cu.get("TotalShares", cu.get("total_shares", cu.get("shares", "")))),
            "total_loans": str(cu.get("TotalLoans", cu.get("total_loans", cu.get("loans", "")))),
            "net_worth": str(cu.get("NetWorth", cu.get("net_worth", ""))),
            "members_count": str(cu.get("MemberCount", cu.get("members_count", cu.get("members", "")))),
            "city": str(cu.get("City", cu.get("city", ""))),
            "state": "PR",
            "source_doc": NCUA_SEARCH_API,
        })
    if rows:
        logger.info(f"  NCUA search API: {len(rows)} PR credit unions")
    return rows


def _fetch_ncua_bulk(session, logger) -> list[dict]:
    rows = []
    current_year = 2024
    for year in range(current_year, 2020, -1):
        for quarter in ["December", "September", "June", "March"]:
            url = (
                f"{NCUA_CALL_REPORT_BASE}/"
                f"call-report-data/{year}/NCUA5300CallReport{quarter}{year}.zip"
            )
            logger.info(f"  Trying NCUA bulk ZIP {quarter} {year}...")
            resp = _get(session, url, {}, logger)
            if not resp or not resp.content:
                url2 = (
                    f"https://www.ncua.gov/files/publications/analysis/call-report-data/"
                    f"{year}/NCUA5300CallReport{quarter}{year}.zip"
                )
                resp = _get(session, url2, {}, logger)
            if not resp or not resp.content:
                continue
            try:
                import zipfile
                zf = zipfile.ZipFile(io.BytesIO(resp.content))
                csv_files = [f for f in zf.namelist() if f.lower().endswith(".csv")]
                for csv_name in csv_files:
                    if "acct" in csv_name.lower() or "fs220" in csv_name.lower():
                        continue
                    with zf.open(csv_name) as f:
                        df = pd.read_csv(f, dtype=str, low_memory=False)
                    state_cols = [c for c in df.columns if c.upper() in ("STATE", "STATE_CODE", "CU_STATE")]
                    if not state_cols:
                        continue
                    df_pr = df[df[state_cols[0]].str.upper().str.contains("PR|PUERTO RICO|72", na=False)]
                    if df_pr.empty:
                        continue
                    for _, r in df_pr.iterrows():
                        rd = r.to_dict()
                        name = str(rd.get("CU_NAME", rd.get("cu_name", rd.get("CreditUnionName", ""))))
                        rows.append({
                            "reporting_period": f"{quarter} {year}",
                            "cu_number": str(rd.get("CU_NUMBER", rd.get("cu_number", rd.get("CUNumber", "")))),
                            "cu_name": name,
                            "cu_normalized": _normalize_name(name),
                            "total_assets": str(rd.get("TOTAL_ASSETS", rd.get("total_assets", rd.get("ACCT_010", "")))),
                            "total_shares": str(rd.get("TOTAL_SHARES", rd.get("total_shares", rd.get("ACCT_018", "")))),
                            "total_loans": str(rd.get("TOTAL_LOANS", rd.get("total_loans", rd.get("ACCT_025B", "")))),
                            "net_worth": str(rd.get("NET_WORTH", rd.get("net_worth", rd.get("ACCT_997", "")))),
                            "members_count": str(rd.get("MEMBER_COUNT", rd.get("members_count", rd.get("ACCT_083", "")))),
                            "city": str(rd.get("CITY", rd.get("city", ""))),
                            "state": "PR",
                            "source_doc": url,
                        })
                if rows:
                    logger.info(f"  NCUA bulk {quarter} {year}: {len(rows)} PR rows")
                    return rows
            except Exception as e:
                logger.warning(f"  Could not parse NCUA ZIP {quarter} {year}: {e}")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_ncua_credit_unions.csv"

    logger = setup_logging("download_ncua")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    search_rows = _fetch_ncua_search_api(session, logger)
    all_rows.extend(search_rows)

    if not all_rows:
        bulk_rows = _fetch_ncua_bulk(session, logger)
        all_rows.extend(bulk_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No NCUA data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://www.ncua.gov/analysis/"
            "credit-union-corporate-call-report-data"
        )
        pd.DataFrame(columns=NCUA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in NCUA_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[NCUA_COLUMNS]
    if "cu_number" in df.columns:
        df = df.drop_duplicates(subset=["cu_number", "reporting_period"], keep="first")
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download NCUA credit union data for Puerto Rico")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nNCUA credit unions: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
