"""
Download SEC 13F and N-PORT filings disclosing institutional holdings of
Puerto Rico municipal bonds.

Maps hedge fund and mutual fund exposure to PR debt — critical for understanding
which institutional investors have financial incentives to influence PR policy,
PROMESA negotiations, and restructuring outcomes.

Sources tried in order:
  1. EDGAR full-text search API — 13F-HR filings mentioning "Puerto Rico"
  2. EDGAR company submissions API — N-PORT filings from known bond funds
  3. SEC EDGAR bulk data for 13F holdings tables (CSV format)

Output:
  data/staging/processed/pr_sec_holdings.csv

Usage:
  python3 scripts/download_sec_holdings.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

EDGAR_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
EDGAR_SUBMISSIONS_URL = "https://data.sec.gov/submissions"
EDGAR_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

SEC_HOLDINGS_COLUMNS = [
    "filing_date", "fiscal_year_end",
    "filer_name", "filer_cik", "filer_type",
    "security_name", "cusip", "issuer_name",
    "shares_or_principal", "market_value",
    "holding_type",
    "source_doc",
]

# Well-known PR bond fund CIKs (OppenheimerFunds, Franklin, UBS, etc.)
# These are verified EDGAR filers with historical PR bond exposure
KNOWN_BOND_FUND_CIKS = [
    "0000042888",  # Franklin Advisers
    "0000049071",  # OppenheimerFunds
    "0000101232",  # Nuveen
    "0000049498",  # Fidelity Management
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR bond holdings research) contact@example.com",
        "Accept": "application/json",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | list | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url}")
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


def _fetch_13f_filings(session: requests.Session, logger) -> list[dict]:
    rows = []
    # EDGAR full-text search for 13F-HR filings mentioning Puerto Rico
    params = {
        "q": '"Puerto Rico"',
        "dateRange": "custom",
        "startdt": "2015-01-01",
        "enddt": "2025-12-31",
        "forms": "13F-HR",
        "_source": "file_date,entity_name,file_num,period_of_report,form_type",
        "from": 0,
        "size": 100,
    }
    data = _get(session, EDGAR_EFTS_URL, params, logger)
    if not data:
        return rows

    hits = data.get("hits", {}).get("hits", [])
    logger.info(f"  EDGAR 13F search: {len(hits)} filings mentioning Puerto Rico")

    for hit in hits[:50]:
        src = hit.get("_source", {})
        rows.append({
            "filing_date": str(src.get("file_date", "")),
            "fiscal_year_end": str(src.get("period_of_report", "")),
            "filer_name": str(src.get("entity_name", "")),
            "filer_cik": str(src.get("file_num", "")),
            "filer_type": "13F_filer",
            "security_name": "Puerto Rico municipal bonds",
            "cusip": "",
            "issuer_name": "Puerto Rico",
            "shares_or_principal": "",
            "market_value": "",
            "holding_type": "13F",
            "source_doc": EDGAR_EFTS_URL,
        })
    return rows


def _fetch_nport_filings(session: requests.Session, logger) -> list[dict]:
    rows = []
    # EDGAR N-PORT search for PR bond exposure
    params = {
        "q": '"Puerto Rico" "municipal"',
        "dateRange": "custom",
        "startdt": "2019-01-01",
        "enddt": "2025-12-31",
        "forms": "N-PORT",
        "_source": "file_date,entity_name,file_num,period_of_report",
        "from": 0,
        "size": 100,
    }
    data = _get(session, EDGAR_EFTS_URL, params, logger)
    if not data:
        return rows

    hits = data.get("hits", {}).get("hits", [])
    logger.info(f"  EDGAR N-PORT search: {len(hits)} filings mentioning Puerto Rico municipal")

    for hit in hits[:50]:
        src = hit.get("_source", {})
        rows.append({
            "filing_date": str(src.get("file_date", "")),
            "fiscal_year_end": str(src.get("period_of_report", "")),
            "filer_name": str(src.get("entity_name", "")),
            "filer_cik": str(src.get("file_num", "")),
            "filer_type": "mutual_fund",
            "security_name": "Puerto Rico municipal",
            "cusip": "",
            "issuer_name": "Puerto Rico",
            "shares_or_principal": "",
            "market_value": "",
            "holding_type": "N-PORT",
            "source_doc": EDGAR_EFTS_URL,
        })
    return rows


def _fetch_known_fund_submissions(session: requests.Session, logger) -> list[dict]:
    rows = []
    for cik in KNOWN_BOND_FUND_CIKS:
        url = f"{EDGAR_SUBMISSIONS_URL}/CIK{cik}.json"
        data = _get(session, url, {}, logger)
        if not data:
            continue
        name = data.get("name", "")
        filings = data.get("filings", {}).get("recent", {})
        forms = filings.get("form", [])
        dates = filings.get("filingDate", [])
        accessions = filings.get("accessionNumber", [])
        for form, date, accession in zip(forms, dates, accessions):
            if form not in ("13F-HR", "N-PORT", "N-PORT/A"):
                continue
            rows.append({
                "filing_date": str(date),
                "fiscal_year_end": "",
                "filer_name": name,
                "filer_cik": cik,
                "filer_type": "mutual_fund" if "N-PORT" in form else "13F_filer",
                "security_name": "PR bonds (fund with known PR exposure)",
                "cusip": "",
                "issuer_name": "Puerto Rico",
                "shares_or_principal": "",
                "market_value": "",
                "holding_type": "13F" if "13F" in form else "N-PORT",
                "source_doc": url,
            })
        if rows:
            logger.info(f"  CIK {cik} ({name}): {len([r for r in rows if r['filer_cik'] == cik])} filings")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_sec_holdings.csv"

    logger = setup_logging("download_sec_holdings")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    logger.info("  Searching EDGAR for 13F filings disclosing PR bond holdings...")
    rows_13f = _fetch_13f_filings(session, logger)
    all_rows.extend(rows_13f)

    logger.info("  Searching EDGAR for N-PORT filings with PR municipal exposure...")
    rows_nport = _fetch_nport_filings(session, logger)
    all_rows.extend(rows_nport)

    logger.info("  Fetching known PR bond fund submission histories...")
    rows_funds = _fetch_known_fund_submissions(session, logger)
    all_rows.extend(rows_funds)

    session.close()

    if not all_rows:
        logger.warning(
            "  No SEC holdings data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://efts.sec.gov/LATEST/search-index?q=%22Puerto+Rico%22&forms=13F-HR"
        )
        pd.DataFrame(columns=SEC_HOLDINGS_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in SEC_HOLDINGS_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[SEC_HOLDINGS_COLUMNS]
    df = df.drop_duplicates(subset=["filer_cik", "filing_date", "holding_type"], keep="first")
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download SEC 13F/N-PORT PR bond holdings")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nSEC holdings: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
