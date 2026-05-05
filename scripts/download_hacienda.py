"""
Download PR Department of Treasury (Hacienda) monthly revenue data.

Hacienda publishes monthly statistical bulletins covering IVU (sales tax),
income tax, excise tax, and other revenue streams. This is the internal
fiscal counterpart to AAFAF's expenditure data.

Sources tried in order:
  1. Hacienda monthly revenue bulletins HTML scrape (hacienda.pr.gov)
  2. AAFAF monthly treasury reports with Hacienda revenue tables
  3. PR data portal CKAN search

Output:
  data/staging/processed/pr_hacienda_revenues.csv

Usage:
  python3 scripts/download_hacienda.py [--force]
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

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

HACIENDA_COLUMNS = [
    "fiscal_year", "month", "revenue_type",
    "amount", "yoy_change_pct", "ytd_amount", "source_doc",
]

HACIENDA_BULLETINS_URL = "https://hacienda.pr.gov/informes/boletines-estadisticos/"
AAFAF_REPORTS_URL = "https://www.aafaf.pr.gov/informes/"
PR_DATA_SEARCH = "https://data.pr.gov/api/3/action/package_search"

MONTH_MAP = {
    "enero": "01", "febrero": "02", "marzo": "03", "abril": "04",
    "mayo": "05", "junio": "06", "julio": "07", "agosto": "08",
    "septiembre": "09", "octubre": "10", "noviembre": "11", "diciembre": "12",
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR Hacienda revenue research)",
        "Accept": "text/html,application/json",
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


def _parse_month_year(text: str):
    text_lower = text.lower()
    for month_name, month_num in MONTH_MAP.items():
        if month_name in text_lower:
            year_match = re.search(r'\b(20\d{2})\b', text)
            if year_match:
                return year_match.group(1), month_num
    return "", ""


def _scrape_hacienda(session, logger) -> list[dict]:
    rows = []
    logger.info("  Scraping Hacienda monthly revenue bulletins...")
    resp = _get(session, HACIENDA_BULLETINS_URL, {}, logger)
    if not resp:
        return rows

    # Extract Excel/PDF bulletin links
    excel_links = re.findall(
        r'href=["\']([^"\']*(?:boletin|ingreso|recaudacion|revenue|estadistico)[^"\']*\.(?:xlsx|xls))["\']',
        resp.text, re.IGNORECASE
    )
    pdf_links = re.findall(
        r'href=["\']([^"\']*(?:boletin|ingreso|recaudacion|revenue)[^"\']*\.pdf)["\']',
        resp.text, re.IGNORECASE
    )
    all_links = excel_links[:10] + pdf_links[:5]

    import io
    for link in all_links:
        url = link if link.startswith("http") else f"https://hacienda.pr.gov{link}"
        if not link.lower().endswith((".xlsx", ".xls")):
            continue
        logger.info(f"  Downloading Hacienda bulletin: {url[:80]}")
        resp2 = _get(session, url, {}, logger)
        if not resp2 or not resp2.content:
            continue
        try:
            xl = pd.ExcelFile(io.BytesIO(resp2.content))
            for sheet in xl.sheet_names[:5]:
                try:
                    df = xl.parse(sheet, dtype=str, header=None)
                except Exception:
                    continue
                # Extract fiscal year and month from filename/URL
                fy, month = _parse_month_year(link)
                # Look for revenue table rows (tax type + amount pattern)
                for idx, row in df.iterrows():
                    row_vals = [str(v) for v in row.values if pd.notna(v) and str(v).strip()]
                    if len(row_vals) < 2:
                        continue
                    rev_type = row_vals[0].strip()
                    # Skip headers and totals rows
                    if len(rev_type) < 3 or rev_type.lower() in ("total", "tipo", "concepto"):
                        continue
                    # Look for numeric amount
                    amount = ""
                    for val in row_vals[1:]:
                        clean = re.sub(r"[,$\s]", "", val)
                        if re.match(r'^-?\d+\.?\d*$', clean):
                            amount = clean
                            break
                    if not amount:
                        continue
                    rows.append({
                        "fiscal_year": fy,
                        "month": month,
                        "revenue_type": rev_type,
                        "amount": amount,
                        "yoy_change_pct": row_vals[3] if len(row_vals) > 3 else "",
                        "ytd_amount": row_vals[4] if len(row_vals) > 4 else "",
                        "source_doc": url,
                    })
                if rows:
                    logger.info(f"  Hacienda bulletin: {len(rows)} revenue rows")
                    return rows
        except Exception as e:
            logger.warning(f"  Could not parse Hacienda bulletin {url[:60]}: {e}")
    return rows


def _fetch_pr_data_portal(session, logger) -> list[dict]:
    rows = []
    logger.info("  Searching PR data portal for Hacienda revenue datasets...")
    params = {"q": "hacienda ingresos recaudacion", "rows": 10}
    resp = _get(session, PR_DATA_SEARCH, params, logger)
    if not resp:
        return rows
    try:
        result = resp.json()
    except Exception:
        return rows
    for pkg in result.get("result", {}).get("results", []):
        for resource in pkg.get("resources", []):
            url = resource.get("url", "")
            fmt = resource.get("format", "").upper()
            if not url or fmt not in ("CSV", "JSON", "XLSX", "XLS"):
                continue
            resp2 = _get(session, url, {}, logger)
            if not resp2 or not resp2.content:
                continue
            try:
                import io
                if fmt in ("XLSX", "XLS"):
                    df = pd.read_excel(io.BytesIO(resp2.content), dtype=str)
                elif fmt == "CSV":
                    df = pd.read_csv(io.BytesIO(resp2.content), dtype=str, low_memory=False)
                else:
                    df = pd.json_normalize(resp2.json())
                for _, r in df.iterrows():
                    rd = r.to_dict()
                    rows.append({
                        "fiscal_year": str(rd.get("fiscal_year", rd.get("año", rd.get("año_fiscal", "")))),
                        "month": str(rd.get("month", rd.get("mes", ""))),
                        "revenue_type": str(rd.get("revenue_type", rd.get("tipo_ingreso", rd.get("concepto", "")))),
                        "amount": str(rd.get("amount", rd.get("monto", rd.get("importe", "")))),
                        "yoy_change_pct": str(rd.get("yoy_change_pct", rd.get("variacion_pct", ""))),
                        "ytd_amount": str(rd.get("ytd_amount", rd.get("acumulado", ""))),
                        "source_doc": url,
                    })
                if rows:
                    logger.info(f"  PR data portal Hacienda: {len(rows)} rows")
                    return rows
            except Exception as e:
                logger.warning(f"  Could not parse {url[:60]}: {e}")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_hacienda_revenues.csv"

    logger = setup_logging("download_hacienda")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    hacienda_rows = _scrape_hacienda(session, logger)
    all_rows.extend(hacienda_rows)

    if not all_rows:
        portal_rows = _fetch_pr_data_portal(session, logger)
        all_rows.extend(portal_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No Hacienda revenue data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://hacienda.pr.gov/informes/boletines-estadisticos/"
        )
        pd.DataFrame(columns=HACIENDA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in HACIENDA_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[HACIENDA_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR Hacienda monthly tax revenue data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nHacienda revenues: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
