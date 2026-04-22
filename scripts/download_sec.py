"""
Download SEC EDGAR financial data for Puerto Rico-significant public companies.

Two groups:
  1. PR-domiciled companies — banks, insurers, holding companies incorporated
     in Puerto Rico (Popular Inc, First BanCorp, OFG Bancorp, Triple-S, etc.)
  2. PR-significant multinationals — pharmaceutical and manufacturing companies
     with major Puerto Rico operations discovered via EDGAR full-text search.

Uses the SEC EDGAR XBRL Company Facts API (no key required) and the
EDGAR full-text search API to discover filers.

Output:
  data/staging/raw/sec/pr_sec_companies.csv    (company profiles)
  data/staging/raw/sec/pr_sec_financials.csv   (key annual financial metrics)
  data/staging/processed/pr_sec_companies.csv
  data/staging/processed/pr_sec_financials.csv

Usage:
  python3 scripts/download_sec.py
  python3 scripts/download_sec.py --force
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

EDGAR_BASE    = "https://data.sec.gov"
EFTS_BASE     = "https://efts.sec.gov"
PAGE_SLEEP    = 0.12   # SEC asks for max 10 req/s; 0.12s gives comfortable headroom
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]

# Known PR-domiciled public companies with confirmed CIKs
PR_DOMICILED = [
    {"cik": "0000763901", "ticker": "BPOP",  "name": "Popular Inc",           "sector": "Banking"},
    {"cik": "0000834494", "ticker": "FBP",   "name": "First BanCorp PR",       "sector": "Banking"},
    {"cik": "0001016178", "ticker": "OFG",   "name": "OFG Bancorp",            "sector": "Banking"},
    {"cik": "0000072778", "ticker": "GTS",   "name": "Triple-S Management",    "sector": "Insurance"},
    {"cik": "0001633931", "ticker": "EVRI",  "name": "Everi Holdings",         "sector": "Gaming"},
    {"cik": "0001001233", "ticker": "PRSC",  "name": "Providence Service",     "sector": "Healthcare"},
]

# Major multinationals with documented large PR manufacturing/operations
# These appear in EDGAR 10-K filings with Puerto Rico revenue/asset disclosures
PR_SIGNIFICANT = [
    {"cik": "0000049826", "ticker": "JNJ",   "name": "Johnson & Johnson",      "sector": "Pharma"},
    {"cik": "0001551152", "ticker": "ABBV",  "name": "AbbVie Inc",             "sector": "Pharma"},
    {"cik": "0000318154", "ticker": "AMGN",  "name": "Amgen Inc",              "sector": "Biotech"},
    {"cik": "0000078814", "ticker": "PFE",   "name": "Pfizer Inc",             "sector": "Pharma"},
    {"cik": "0000014272", "ticker": "BMY",   "name": "Bristol-Myers Squibb",   "sector": "Pharma"},
    {"cik": "0000059478", "ticker": "MRK",   "name": "Merck & Co",             "sector": "Pharma"},
    {"cik": "0000310764", "ticker": "LLY",   "name": "Eli Lilly",              "sector": "Pharma"},
    {"cik": "0000047111", "ticker": "HON",   "name": "Honeywell International","sector": "Industrial"},
    {"cik": "0001090872", "ticker": "ELV",   "name": "Elevance Health",        "sector": "Insurance"},
]

COMPANY_COLUMNS = [
    "cik", "ticker", "name", "sector", "pr_domiciled",
    "sic", "sic_description", "state_of_inc", "fiscal_year_end",
    "latest_10k_date", "total_employees",
]

FINANCIAL_COLUMNS = [
    "cik", "ticker", "name", "fiscal_year",
    "total_revenues", "net_income", "total_assets",
    "total_liabilities", "stockholders_equity",
    "operating_income", "r_and_d_expense",
    "shares_outstanding",
]

# XBRL concept names to pull (US-GAAP taxonomy)
XBRL_CONCEPTS = {
    "total_revenues":       ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                             "SalesRevenueNet", "RevenuesNetOfInterestExpense"],
    "net_income":           ["NetIncomeLoss", "ProfitLoss"],
    "total_assets":         ["Assets"],
    "total_liabilities":    ["Liabilities"],
    "stockholders_equity":  ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "operating_income":     ["OperatingIncomeLoss"],
    "r_and_d_expense":      ["ResearchAndDevelopmentExpense"],
    "shares_outstanding":   ["CommonStockSharesOutstanding"],
    "total_employees":      ["EntityNumberOfEmployees"],
}


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper research@pr-pipeline.org",  # SEC requires contact info
        "Accept":     "application/json",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | list | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  SEC rate limit — sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code == 404:
                return None
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url[:80]}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({exc}) — retry in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed for {url[:80]}: {exc}")
    return None


# ---------------------------------------------------------------------------
# EDGAR full-text search: discover additional PR-significant 10-K filers
# ---------------------------------------------------------------------------

def _discover_pr_filers(session: requests.Session, logger) -> list[dict]:
    """Find 10-K filers that prominently mention Puerto Rico operations."""
    url = f"{EFTS_BASE}/LATEST/search-index"
    params = {
        "q":        '"Puerto Rico" "manufacturing" OR "operations"',
        "forms":    "10-K",
        "dateRange": "custom",
        "startdt":  "2018-01-01",
        "enddt":    __import__("datetime").date.today().strftime("%Y-%m-%d"),
    }
    data = _get(session, url, params, logger)
    if not data:
        return []

    hits  = data.get("hits", {}).get("hits", [])
    known_ciks = {e["cik"] for e in PR_DOMICILED + PR_SIGNIFICANT}
    discovered = []
    for hit in hits:
        src = hit.get("_source", {})
        cik = str(src.get("entity_id", "")).zfill(10)
        if cik and cik not in known_ciks:
            discovered.append({
                "cik":    cik,
                "ticker": "",
                "name":   src.get("display_names", [""])[0] if src.get("display_names") else "",
                "sector": "Discovered",
            })
            known_ciks.add(cik)

    logger.info(f"  EDGAR full-text search: {len(discovered)} additional filers discovered")
    return discovered


# ---------------------------------------------------------------------------
# Fetch company submission metadata
# ---------------------------------------------------------------------------

def _fetch_submissions(session: requests.Session, cik: str, logger) -> dict:
    url  = f"{EDGAR_BASE}/submissions/CIK{cik}.json"
    data = _get(session, url, {}, logger)
    return data or {}


# ---------------------------------------------------------------------------
# Fetch XBRL company facts and extract annual time series
# ---------------------------------------------------------------------------

def _fetch_xbrl_facts(session: requests.Session, cik: str, logger) -> dict:
    url  = f"{EDGAR_BASE}/api/xbrl/companyfacts/CIK{cik}.json"
    data = _get(session, url, {}, logger)
    return data or {}


def _extract_annual_series(facts: dict, concept_names: list[str],
                           unit_filter: str = "USD") -> list[tuple[int, float]]:
    """
    From XBRL facts, return a list of (fiscal_year, value) pairs for
    annual 10-K filings. Tries each concept name in order.
    """
    us_gaap = facts.get("facts", {}).get("us-gaap", {})
    dei     = facts.get("facts", {}).get("dei", {})

    for concept in concept_names:
        for taxonomy in (us_gaap, dei):
            node = taxonomy.get(concept)
            if not node:
                continue
            units = node.get("units", {})
            for unit_key, entries in units.items():
                if unit_filter and unit_key != unit_filter and unit_filter != "any":
                    continue
                annual = [
                    e for e in entries
                    if e.get("form") in ("10-K", "10-K405", "10-KSB")
                    and e.get("end") and e.get("val") is not None
                    and e.get("fp") == "FY"
                ]
                if annual:
                    # Deduplicate by (end date) keeping latest filed
                    by_end = {}
                    for e in annual:
                        end = e["end"][:4]  # fiscal year
                        if end not in by_end or e.get("filed", "") > by_end[end].get("filed", ""):
                            by_end[end] = e
                    return [(int(yr), float(e["val"])) for yr, e in sorted(by_end.items())]
    return []


# ---------------------------------------------------------------------------
# Build financial rows for one company
# ---------------------------------------------------------------------------

def _company_financials(cik: str, ticker: str, name: str, facts: dict) -> list[dict]:
    series_by_concept = {}
    for field, concepts in XBRL_CONCEPTS.items():
        unit = "pure" if field in ("shares_outstanding",) else \
               "any"  if field == "total_employees" else "USD"
        series = _extract_annual_series(facts, concepts, unit_filter=unit)
        for yr, val in series:
            series_by_concept.setdefault(yr, {})[field] = val

    rows = []
    for yr in sorted(series_by_concept.keys()):
        row = {"cik": cik, "ticker": ticker, "name": name, "fiscal_year": yr}
        row.update(series_by_concept[yr])
        for col in FINANCIAL_COLUMNS:
            row.setdefault(col, None)
        rows.append({k: row[k] for k in FINANCIAL_COLUMNS if k in row})
    return rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "sec"
    out_dir = root / "data" / "staging" / "processed"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    co_raw_path  = raw_dir / "pr_sec_companies.csv"
    fin_raw_path = raw_dir / "pr_sec_financials.csv"
    co_out_path  = out_dir / "pr_sec_companies.csv"
    fin_out_path = out_dir / "pr_sec_financials.csv"

    logger  = setup_logging("download_sec")
    session = _session()

    if not force and co_raw_path.exists() and fin_raw_path.exists():
        logger.info("  Cached SEC files exist — loading")
        df_co  = pd.read_csv(co_raw_path,  dtype=str, low_memory=False)
        df_fin = pd.read_csv(fin_raw_path, dtype=str, low_memory=False)
        df_co.to_csv(co_out_path,  index=False, encoding="utf-8")
        df_fin.to_csv(fin_out_path, index=False, encoding="utf-8")
        return {
            "company_rows":   len(df_co),
            "financial_rows": len(df_fin),
            "status": "OK",
        }

    # Build full company list
    logger.info("Discovering PR-significant SEC filers...")
    discovered = _discover_pr_filers(session, logger)
    all_companies = (
        [dict(e, pr_domiciled=True)  for e in PR_DOMICILED] +
        [dict(e, pr_domiciled=False) for e in PR_SIGNIFICANT] +
        [dict(e, pr_domiciled=False) for e in discovered]
    )
    logger.info(f"  Total companies to profile: {len(all_companies):,}")

    co_rows  = []
    fin_rows = []

    for i, co in enumerate(all_companies, 1):
        cik    = str(co["cik"]).zfill(10)
        ticker = co.get("ticker", "")
        name   = co.get("name", "")
        logger.info(f"  [{i}/{len(all_companies)}] {name or cik} ({ticker})")

        # Submission metadata
        sub = _fetch_submissions(session, cik, logger)
        if not sub:
            continue

        co_info = sub.get("entityType", "")
        sic     = str(sub.get("sic", ""))
        sic_desc = sub.get("sicDescription", "")
        state   = sub.get("stateOfIncorporation", "")
        fy_end  = sub.get("fiscalYearEnd", "")

        # Find most recent 10-K date
        recent_filings = sub.get("filings", {}).get("recent", {})
        forms = recent_filings.get("form", [])
        dates = recent_filings.get("filingDate", [])
        latest_10k = ""
        for form, date in zip(forms, dates):
            if form in ("10-K", "10-K405", "10-KSB"):
                latest_10k = date
                break

        co_rows.append({
            "cik":            cik,
            "ticker":         ticker,
            "name":           sub.get("name") or name,
            "sector":         co.get("sector", ""),
            "pr_domiciled":   co.get("pr_domiciled", False),
            "sic":            sic,
            "sic_description": sic_desc,
            "state_of_inc":   state,
            "fiscal_year_end": fy_end,
            "latest_10k_date": latest_10k,
            "total_employees": "",  # filled from XBRL below
        })

        # XBRL company facts
        facts = _fetch_xbrl_facts(session, cik, logger)
        if facts:
            rows = _company_financials(cik, ticker, sub.get("name") or name, facts)
            fin_rows.extend(rows)
            # Back-fill employee count into co_rows from most recent year
            emp_series = _extract_annual_series(facts, ["EntityNumberOfEmployees"], unit_filter="any")
            if emp_series:
                co_rows[-1]["total_employees"] = emp_series[-1][1]

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    df_co = pd.DataFrame(co_rows)
    for col in COMPANY_COLUMNS:
        if col not in df_co.columns:
            df_co[col] = ""
    df_co = df_co[COMPANY_COLUMNS]

    df_fin = pd.DataFrame(fin_rows)
    for col in FINANCIAL_COLUMNS:
        if col not in df_fin.columns:
            df_fin[col] = ""
    df_fin = df_fin[FINANCIAL_COLUMNS]
    # Keep only last 10 years per company
    df_fin = df_fin[pd.to_numeric(df_fin["fiscal_year"], errors="coerce").fillna(0) >= 2014]

    df_co.to_csv(co_raw_path,  index=False, encoding="utf-8")
    df_fin.to_csv(fin_raw_path, index=False, encoding="utf-8")
    df_co.to_csv(co_out_path,  index=False, encoding="utf-8")
    df_fin.to_csv(fin_out_path, index=False, encoding="utf-8")

    session.close()

    logger.info("=" * 60)
    logger.info("SEC EDGAR DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Companies profiled:    {len(df_co):,}")
    logger.info(f"  Financial data rows:   {len(df_fin):,} (annual 10-K metrics)")

    if not df_fin.empty:
        df_latest = (
            df_fin
            .sort_values("fiscal_year", ascending=False)
            .drop_duplicates("cik")
            .sort_values("total_revenues", ascending=False, key=lambda s: pd.to_numeric(s, errors="coerce").fillna(0))
        )
        logger.info(f"\n  Top 10 by latest revenue:")
        for _, row in df_latest.head(10).iterrows():
            rev = pd.to_numeric(row.get("total_revenues"), errors="coerce")
            rev_str = f"${rev / 1e9:>7.1f}B" if pd.notna(rev) and rev > 0 else "      N/A"
            sector = str(row.get("sector", ""))[:20]
            logger.info(f"    {str(row.get('name', ''))[:50]:<50} {rev_str}  [{sector}]  FY{row.get('fiscal_year', '')}")

    return {
        "company_rows":   len(df_co),
        "financial_rows": len(df_fin),
        "status": "OK" if len(df_co) > 0 else "EMPTY",
        "co_path":  str(co_out_path),
        "fin_path": str(fin_out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download SEC EDGAR data for PR-significant companies")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nSEC EDGAR download complete. {result['company_rows']:,} companies, "
          f"{result['financial_rows']:,} annual financial rows.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
