"""
Download AAFAF (Autoridad de Asesoría Financiera y Agencia Fiscal de Puerto Rico)
monthly treasury reports and certified fiscal plan budget execution data.

AAFAF manages PR's $35B annual government budget and publishes monthly cash flow
reports showing actual revenues vs. expenditures vs. certified fiscal plan targets.
This is the primary source for PR government budget execution data.

Sources tried in order:
  1. AAFAF monthly reports index page — HTML scrape for Excel/PDF download links
  2. PR data portal CKAN API — data.pr.gov search for AAFAF datasets
  3. AAFAF fiscal plan page — certified budget vs. actual comparison tables

Outputs:
  data/staging/processed/pr_aafaf_budget.csv

Usage:
  python3 scripts/download_aafaf.py [--force]
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

AAFAF_REPORTS_URL = "https://www.aafaf.pr.gov/informes/"
AAFAF_FISCAL_PLAN_URL = "https://www.aafaf.pr.gov/fiscal-plan/"
PR_DATA_PORTAL_URL = "https://data.pr.gov/api/3/action/package_search"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

AAFAF_COLUMNS = [
    "fiscal_year",
    "month",
    "report_type",
    "revenue_category",
    "revenue_amount",
    "expenditure_category",
    "expenditure_amount",
    "cash_balance",
    "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR AAFAF budget research)",
        "Accept": "text/html,application/xhtml+xml,application/json",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger, accept_html: bool = False) -> requests.Response | None:
    headers = {}
    if accept_html:
        headers["Accept"] = "text/html,application/xhtml+xml"
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, headers=headers, timeout=60)
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


def _find_excel_links(html: str, base_url: str) -> list[str]:
    """Extract Excel and CSV download links from HTML."""
    pattern = r'href=["\']([^"\']*\.(?:xlsx|xls|csv))["\']'
    links = re.findall(pattern, html, re.IGNORECASE)
    result = []
    for link in links:
        if link.startswith("http"):
            result.append(link)
        elif link.startswith("/"):
            from urllib.parse import urlparse
            parsed = urlparse(base_url)
            result.append(f"{parsed.scheme}://{parsed.netloc}{link}")
        else:
            result.append(f"{base_url.rstrip('/')}/{link}")
    return result


def _parse_excel_to_records(content: bytes, url: str, logger) -> list[dict]:
    """Parse Excel file content into normalized records."""
    rows = []
    try:
        df = pd.read_excel(pd.io.common.BytesIO(content), sheet_name=None, header=None)
        for sheet_name, sheet_df in (df.items() if isinstance(df, dict) else [("Sheet1", df)]):
            # Try to detect if this looks like financial data
            text_vals = sheet_df.astype(str).values.flatten()
            has_financial = any(
                kw in str(v).lower()
                for v in text_vals
                for kw in ["revenue", "expenditure", "balance", "ingresos", "gastos", "balance"]
            )
            if not has_financial:
                continue

            # Try reading with auto-detected header
            try:
                sheet_df2 = pd.read_excel(pd.io.common.BytesIO(content), sheet_name=sheet_name)
                if len(sheet_df2) > 0 and len(sheet_df2.columns) > 1:
                    sheet_df2["source_doc"] = url
                    sheet_df2["report_type"] = "monthly_treasury"
                    rows.extend(sheet_df2.to_dict("records"))
                    logger.info(f"  Sheet '{sheet_name}': {len(sheet_df2)} rows")
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"  Excel parse failed for {url}: {e}")
    return rows


def _fetch_aafaf_reports(session: requests.Session, logger) -> list[dict]:
    """Scrape AAFAF reports index for downloadable Excel files."""
    rows = []
    resp = _get(session, AAFAF_REPORTS_URL, {}, logger, accept_html=True)
    if not resp:
        logger.warning("  AAFAF reports page not accessible")
        return rows

    links = _find_excel_links(resp.text, AAFAF_REPORTS_URL)
    logger.info(f"  Found {len(links)} Excel/CSV links on AAFAF reports page")

    for url in links[:20]:
        try:
            file_resp = session.get(url, timeout=60)
            if file_resp.status_code == 200:
                records = _parse_excel_to_records(file_resp.content, url, logger)
                rows.extend(records)
        except Exception as e:
            logger.debug(f"  Could not download {url}: {e}")
        time.sleep(PAGE_SLEEP)

    return rows


def _fetch_pr_data_portal(session: requests.Session, logger) -> list[dict]:
    """Search PR Open Data portal for AAFAF/budget datasets."""
    rows = []
    try:
        resp = _get(session, PR_DATA_PORTAL_URL, {"q": "aafaf presupuesto budget", "rows": 20}, logger)
        if not resp:
            return rows
        data = resp.json() if hasattr(resp, "json") else {}
        results = data.get("result", {}).get("results", [])
        for pkg in results:
            for resource in pkg.get("resources", []):
                url = resource.get("url", "")
                fmt = resource.get("format", "").lower()
                if fmt in ("csv", "xlsx", "xls") and url:
                    try:
                        file_resp = session.get(url, timeout=60)
                        if file_resp.status_code == 200:
                            if fmt == "csv":
                                df = pd.read_csv(pd.io.common.BytesIO(file_resp.content), low_memory=False)
                                df["source_doc"] = url
                                df["report_type"] = "pr_data_portal"
                                rows.extend(df.to_dict("records"))
                                logger.info(f"  PR data portal: {len(df)} rows from {url.split('/')[-1]}")
                            else:
                                records = _parse_excel_to_records(file_resp.content, url, logger)
                                rows.extend(records)
                    except Exception as e:
                        logger.debug(f"  Could not fetch {url}: {e}")
                    time.sleep(PAGE_SLEEP)
    except Exception as e:
        logger.warning(f"  PR data portal search failed: {e}")
    return rows


def _normalize_records(records: list[dict], logger) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=AAFAF_COLUMNS)

    df = pd.json_normalize(records)

    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_").replace(" ", "_")
        if ("year" in cl or "año" in cl or "fiscal" in cl) and "fiscal_year" not in rename.values():
            rename[col] = "fiscal_year"
        elif "month" in cl or "mes" in cl and "month" not in rename.values():
            rename[col] = "month"
        elif "report_type" in cl:
            rename[col] = "report_type"
        elif ("revenue" in cl or "ingreso" in cl) and "category" in cl and "revenue_category" not in rename.values():
            rename[col] = "revenue_category"
        elif ("revenue" in cl or "ingreso" in cl) and "amount" in cl and "revenue_amount" not in rename.values():
            rename[col] = "revenue_amount"
        elif ("expenditure" in cl or "gasto" in cl) and "category" in cl and "expenditure_category" not in rename.values():
            rename[col] = "expenditure_category"
        elif ("expenditure" in cl or "gasto" in cl) and "amount" in cl and "expenditure_amount" not in rename.values():
            rename[col] = "expenditure_amount"
        elif "balance" in cl and "cash_balance" not in rename.values():
            rename[col] = "cash_balance"

    df = df.rename(columns=rename)

    for col in AAFAF_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    logger.info(f"  Normalized {len(df):,} AAFAF records")
    return df[AAFAF_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_aafaf_budget.csv"

    logger = setup_logging("download_aafaf")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_records: list[dict] = []

    logger.info("  Fetching AAFAF monthly treasury reports...")
    aafaf_records = _fetch_aafaf_reports(session, logger)
    all_records.extend(aafaf_records)

    if not all_records:
        logger.info("  Trying PR Open Data portal for AAFAF datasets...")
        portal_records = _fetch_pr_data_portal(session, logger)
        all_records.extend(portal_records)

    session.close()

    if not all_records:
        logger.warning(
            "  No AAFAF data retrieved — site may require authentication or be unavailable.\n"
            "  Manual alternative: download monthly treasury reports from\n"
            f"  {AAFAF_REPORTS_URL}"
        )
        pd.DataFrame(columns=AAFAF_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = _normalize_records(all_records, logger)
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")

    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR AAFAF budget execution data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nAAFAF budget: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
