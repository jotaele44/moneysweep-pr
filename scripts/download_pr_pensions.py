"""
Download Puerto Rico public pension fund data for ERS, TRS, and JRS.

PR's three main pension systems have combined liabilities exceeding $50B:
  - ERS (Employees Retirement System / Sistema de Retiro) — general government employees
  - TRS (Teachers Retirement System / Retiro Magisterial) — public school teachers
  - JRS (Judges Retirement System) — judicial branch

These funds are central to PROMESA restructuring and the fiscal crisis.
Data is largely from annual actuarial reports (PDFs/Excel on agency sites).

Sources tried in order:
  1. PROMESA Oversight Board pension documents — most structured public source
  2. ERS annual report Excel/PDF: retiro.pr.gov
  3. AAFAF pension disclosure documents
  4. PR data portal for pension datasets

Outputs:
  data/staging/processed/pr_pension_funds.csv

Usage:
  python3 scripts/download_pr_pensions.py [--force]
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

OVERSIGHT_BOARD_BASE = "https://oversightboard.pr.gov"
ERS_BASE = "https://www.retiro.pr.gov"
AAFAF_PENSION_URL = "https://www.aafaf.pr.gov/pension/"
PR_DATA_PORTAL_URL = "https://data.pr.gov/api/3/action/package_search"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

PENSION_COLUMNS = [
    "fiscal_year",
    "fund_name",
    "total_assets",
    "total_liabilities",
    "net_position",
    "funded_ratio",
    "benefit_payments",
    "employer_contributions",
    "employee_contributions",
    "investment_return_pct",
    "active_members",
    "retirees_count",
    "source_doc",
]

# Known pension fund names
FUND_NAMES = ["ERS", "TRS", "JRS", "Sistema de Retiro", "Retiro Magisterial"]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR pension fund research)",
        "Accept": "text/html,application/json",
    })
    return s


def _get(session: requests.Session, url: str, logger) -> requests.Response | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, timeout=60)
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


def _find_download_links(html: str, base_url: str, extensions: tuple = (".xlsx", ".xls", ".csv")) -> list[str]:
    """Extract file download links from HTML."""
    ext_pattern = "|".join(re.escape(e) for e in extensions)
    pattern = rf'href=["\']([^"\']*(?:{ext_pattern}))["\']'
    links = re.findall(pattern, html, re.IGNORECASE)
    result = []
    for link in links:
        if link.startswith("http"):
            result.append(link)
        elif link.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            result.append(f"{parsed.scheme}://{parsed.netloc}{link}")
    return list(dict.fromkeys(result))  # deduplicate preserving order


def _parse_pension_excel(content: bytes, url: str, fund_hint: str, logger) -> list[dict]:
    """Parse Excel file for pension fund financial metrics."""
    rows = []
    try:
        all_sheets = pd.read_excel(pd.io.common.BytesIO(content), sheet_name=None, header=None)
        for sheet_name, raw_df in (all_sheets.items() if isinstance(all_sheets, dict) else [("Sheet1", all_sheets)]):
            text_flat = raw_df.astype(str).values.flatten()
            pension_keywords = ["assets", "liabilities", "funded", "contributions", "activos", "pasivos", "beneficiarios"]
            if not any(kw in str(v).lower() for v in text_flat for kw in pension_keywords):
                continue
            try:
                df = pd.read_excel(pd.io.common.BytesIO(content), sheet_name=sheet_name)
                if len(df) == 0:
                    continue
                # Try to detect fiscal year column
                fy_col = None
                for col in df.columns:
                    if "year" in str(col).lower() or "año" in str(col).lower() or "fiscal" in str(col).lower():
                        fy_col = col
                        break
                record = {"source_doc": url, "fund_name": fund_hint, "report_type": "annual_report"}
                if fy_col:
                    years = pd.to_numeric(df[fy_col], errors="coerce").dropna()
                    if not years.empty:
                        record["fiscal_year"] = int(years.iloc[-1])
                # Scan for key metrics
                for col in df.columns:
                    cl = str(col).lower()
                    vals = pd.to_numeric(df[col], errors="coerce").dropna()
                    if vals.empty:
                        continue
                    last_val = float(vals.iloc[-1])
                    if "total" in cl and "asset" in cl:
                        record["total_assets"] = last_val
                    elif "liabilit" in cl:
                        record["total_liabilities"] = last_val
                    elif "net" in cl and ("position" in cl or "asset" in cl):
                        record["net_position"] = last_val
                    elif "funded" in cl:
                        record["funded_ratio"] = last_val
                    elif "benefit" in cl and "payment" in cl:
                        record["benefit_payments"] = last_val
                    elif "employer" in cl and "contribut" in cl:
                        record["employer_contributions"] = last_val
                    elif "employee" in cl and "contribut" in cl:
                        record["employee_contributions"] = last_val
                    elif "return" in cl or "rendimiento" in cl:
                        record["investment_return_pct"] = last_val
                    elif "active" in cl and "member" in cl:
                        record["active_members"] = int(last_val)
                    elif "retiree" in cl or "pensionado" in cl:
                        record["retirees_count"] = int(last_val)
                if len(record) > 3:
                    rows.append(record)
                    logger.info(f"  Parsed pension metrics from {url.split('/')[-1]} sheet '{sheet_name}'")
            except Exception as e:
                logger.debug(f"  Sheet parse failed: {e}")
    except Exception as e:
        logger.debug(f"  Excel parse failed for {url}: {e}")
    return rows


def _fetch_from_site(session: requests.Session, base_url: str, fund_name: str, logger) -> list[dict]:
    """Fetch pension data from a specific agency website."""
    rows = []
    resp = _get(session, base_url, logger)
    if not resp:
        return rows

    links = _find_download_links(resp.text, base_url)
    logger.info(f"  {fund_name}: found {len(links)} download links on {base_url}")

    for url in links[:10]:
        try:
            file_resp = session.get(url, timeout=60)
            if file_resp.status_code == 200:
                records = _parse_pension_excel(file_resp.content, url, fund_name, logger)
                rows.extend(records)
        except Exception as e:
            logger.debug(f"  Could not download {url}: {e}")
        time.sleep(PAGE_SLEEP)

    return rows


def _fetch_oversight_board_pension(session: requests.Session, logger) -> list[dict]:
    """Fetch pension analysis documents from the PROMESA Oversight Board."""
    rows = []
    search_urls = [
        f"{OVERSIGHT_BOARD_BASE}/pension/",
        f"{OVERSIGHT_BOARD_BASE}/pension-reform/",
        f"{OVERSIGHT_BOARD_BASE}/documents/?category=pension",
    ]
    for url in search_urls:
        resp = _get(session, url, logger)
        if not resp:
            continue
        links = _find_download_links(resp.text, OVERSIGHT_BOARD_BASE)
        for dl_url in links[:5]:
            try:
                file_resp = session.get(dl_url, timeout=60)
                if file_resp.status_code == 200:
                    records = _parse_pension_excel(file_resp.content, dl_url, "ERS/TRS/JRS", logger)
                    rows.extend(records)
            except Exception as e:
                logger.debug(f"  OB download failed {dl_url}: {e}")
            time.sleep(PAGE_SLEEP)
        if rows:
            break
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_pension_funds.csv"

    logger = setup_logging("download_pr_pensions")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_records: list[dict] = []

    logger.info("  Fetching pension data from PROMESA Oversight Board...")
    ob_records = _fetch_oversight_board_pension(session, logger)
    all_records.extend(ob_records)

    logger.info("  Fetching ERS annual reports...")
    ers_records = _fetch_from_site(session, ERS_BASE, "ERS", logger)
    all_records.extend(ers_records)

    session.close()

    if not all_records:
        logger.warning(
            "  No pension fund data retrieved — annual reports are primarily PDFs.\n"
            "  Manual alternative: download actuarial reports from\n"
            f"  {ERS_BASE} (ERS), and oversightboard.pr.gov (pension analysis)"
        )
        pd.DataFrame(columns=PENSION_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.json_normalize(all_records)

    for col in PENSION_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[PENSION_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")

    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR pension fund data (ERS/TRS/JRS)")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nPR pension funds: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
