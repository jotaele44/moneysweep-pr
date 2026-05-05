"""
Download USDA FNS Nutrition Assistance Program (NAP) data for Puerto Rico.

PR receives a block grant (~$2B/year) instead of regular SNAP because it is a
territory; the program is called NAP (Programa de Asistencia Nutricional).
This is one of the largest single federal transfer payments to PR and was
entirely untracked by the pipeline prior to this script.

Sources tried in order:
  1. USDA FNS annual program data (data.fns.usda.gov) — NAP/SNAP state summaries
  2. data.gov CKAN API — USDA FNS datasets with PR keyword
  3. USASpending fallback — CFDA 10.551/10.561 PR awards

Output:
  data/staging/processed/pr_snap_nap.csv

Usage:
  python3 scripts/download_snap_nap.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

FNS_DATA_BASE = "https://www.fns.usda.gov"
FNS_CKAN_URL = "https://data.fns.usda.gov/api/3/action/package_search"
DATAGOV_CKAN_URL = "https://catalog.data.gov/api/3/action/package_search"
USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

SNAP_NAP_COLUMNS = [
    "fiscal_year", "quarter", "program_type",
    "total_participants", "total_issuances",
    "federal_expenditure", "administrative_cost",
    "avg_benefit_per_household", "source_doc",
]

# USDA FNS NAP-specific program data endpoints (stable URLs)
FNS_NAP_URLS = [
    "https://www.fns.usda.gov/pd/nutrition-assistance-program-nap-puerto-rico",
    "https://www.fns.usda.gov/pd/snap-and-nap-program-data",
    "https://www.fns.usda.gov/nap/nap-data-tables",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR NAP nutrition assistance research)",
        "Accept": "application/json, text/html",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> requests.Response | None:
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


def _post(session: requests.Session, url: str, payload: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, json=payload, timeout=60)
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


def _find_excel_csv_links(html: str, base_url: str) -> list[str]:
    import re
    from urllib.parse import urlparse
    pattern = r'href=["\']([^"\']*\.(?:xlsx|xls|csv))["\']'
    links = re.findall(pattern, html, re.IGNORECASE)
    result = []
    for link in links:
        if link.startswith("http"):
            result.append(link)
        elif link.startswith("/"):
            parsed = urlparse(base_url)
            result.append(f"{parsed.scheme}://{parsed.netloc}{link}")
    return list(dict.fromkeys(result))


def _parse_fns_excel(content: bytes, url: str, logger) -> list[dict]:
    rows = []
    try:
        sheets = pd.read_excel(pd.io.common.BytesIO(content), sheet_name=None, header=None)
        for sheet_name, raw_df in (sheets.items() if isinstance(sheets, dict) else [("Sheet1", sheets)]):
            flat = raw_df.astype(str).values.flatten()
            has_nap = any(kw in str(v).lower() for v in flat
                         for kw in ["nap", "nutrition", "participant", "issuance", "benefit", "puerto rico", "pr"])
            if not has_nap:
                continue
            try:
                df = pd.read_excel(pd.io.common.BytesIO(content), sheet_name=sheet_name)
                if len(df) == 0:
                    continue
                for _, row in df.iterrows():
                    record = {"source_doc": url, "program_type": "NAP"}
                    row_str = {str(k).lower(): str(v) for k, v in row.items()}
                    for k, v in row_str.items():
                        if "year" in k or "fiscal" in k:
                            record["fiscal_year"] = v
                        elif "quarter" in k or "qtr" in k:
                            record["quarter"] = v
                        elif "participant" in k or "household" in k and "count" in k:
                            record["total_participants"] = v
                        elif "issuance" in k or "benefit" in k and "total" in k:
                            record["total_issuances"] = v
                        elif "expenditure" in k or "federal" in k and "cost" in k:
                            record["federal_expenditure"] = v
                        elif "admin" in k:
                            record["administrative_cost"] = v
                        elif "average" in k or "avg" in k:
                            record["avg_benefit_per_household"] = v
                    if len(record) > 2:
                        rows.append(record)
            except Exception as e:
                logger.debug(f"  Sheet parse failed: {e}")
    except Exception as e:
        logger.debug(f"  Excel parse failed: {e}")
    return rows


def _fetch_fns_pages(session: requests.Session, logger) -> list[dict]:
    rows = []
    for url in FNS_NAP_URLS:
        resp = _get(session, url, {}, logger)
        if not resp:
            continue
        links = _find_excel_csv_links(resp.text, url)
        logger.info(f"  FNS page {url.split('/')[-1]}: {len(links)} download links")
        for dl_url in links[:10]:
            try:
                file_resp = session.get(dl_url, timeout=60)
                if file_resp.status_code == 200:
                    if dl_url.endswith(".csv"):
                        df = pd.read_csv(pd.io.common.BytesIO(file_resp.content), low_memory=False)
                        for _, row in df.iterrows():
                            row_dict = row.to_dict()
                            row_dict["source_doc"] = dl_url
                            row_dict["program_type"] = "NAP"
                            rows.append(row_dict)
                    else:
                        records = _parse_fns_excel(file_resp.content, dl_url, logger)
                        rows.extend(records)
            except Exception as e:
                logger.debug(f"  Could not download {dl_url}: {e}")
            time.sleep(PAGE_SLEEP)
        if rows:
            break
    return rows


def _fetch_datagov(session: requests.Session, logger) -> list[dict]:
    rows = []
    try:
        resp = _get(session, DATAGOV_CKAN_URL,
                    {"q": "usda fns nap nutrition assistance puerto rico", "rows": 10}, logger)
        if not resp:
            return rows
        data = resp.json()
        packages = data.get("result", {}).get("results", [])
        for pkg in packages:
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
                                df["program_type"] = "NAP"
                                pr_mask = df.astype(str).apply(
                                    lambda col: col.str.contains("puerto rico|\\bPR\\b", case=False, na=False)
                                ).any(axis=1)
                                df = df[pr_mask]
                                rows.extend(df.to_dict("records"))
                                logger.info(f"  data.gov: {len(df)} PR rows from {url.split('/')[-1]}")
                    except Exception as e:
                        logger.debug(f"  Could not fetch {url}: {e}")
    except Exception as e:
        logger.warning(f"  data.gov search failed: {e}")
    return rows


def _fetch_usaspending_nap(session: requests.Session, logger) -> list[dict]:
    rows = []
    # CFDA 10.551 = Food Stamps/SNAP, 10.559 = Summer Food, broader USDA FNS programs
    cfda_codes = ["10.551", "10.559", "10.568"]
    for cfda in cfda_codes:
        page = 1
        while True:
            payload = {
                "filters": {
                    "award_type_codes": ["02", "03", "04", "05"],
                    "program_numbers": [cfda],
                    "place_of_performance_locations": [{"country": "USA", "state": "PR"}],
                },
                "fields": ["Award ID", "Recipient Name", "Award Amount", "Start Date", "Description"],
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
            for r in results:
                rows.append({
                    "fiscal_year": "",
                    "quarter": "",
                    "program_type": f"USDA_CFDA_{cfda}",
                    "total_participants": "",
                    "total_issuances": str(r.get("Award Amount", "")),
                    "federal_expenditure": str(r.get("Award Amount", "")),
                    "administrative_cost": "",
                    "avg_benefit_per_household": "",
                    "source_doc": f"usaspending_{cfda}",
                })
            if not data.get("page_metadata", {}).get("has_next_page", False):
                break
            page += 1
        time.sleep(PAGE_SLEEP)
    if rows:
        logger.info(f"  USASpending NAP/SNAP fallback: {len(rows):,} records")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_snap_nap.csv"

    logger = setup_logging("download_snap_nap")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    logger.info("  Fetching USDA FNS NAP data from FNS program pages...")
    fns_rows = _fetch_fns_pages(session, logger)
    all_rows.extend(fns_rows)

    if not all_rows:
        logger.info("  Trying data.gov CKAN for USDA FNS NAP datasets...")
        gov_rows = _fetch_datagov(session, logger)
        all_rows.extend(gov_rows)

    if not all_rows:
        logger.info("  Trying USASpending USDA FNS grant fallback...")
        usa_rows = _fetch_usaspending_nap(session, logger)
        all_rows.extend(usa_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No NAP data retrieved. PR block grant data may require direct FNS contact.\n"
            "  Manual alternative: https://www.fns.usda.gov/pd/nutrition-assistance-program-nap-puerto-rico"
        )
        pd.DataFrame(columns=SNAP_NAP_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.json_normalize(all_rows)

    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_")
        if "year" in cl and "fiscal_year" not in rename.values():
            rename[col] = "fiscal_year"
        elif "quarter" in cl and "quarter" not in rename.values():
            rename[col] = "quarter"
        elif "participant" in cl and "total_participants" not in rename.values():
            rename[col] = "total_participants"
        elif "issuance" in cl and "total_issuances" not in rename.values():
            rename[col] = "total_issuances"
        elif "expenditure" in cl and "federal_expenditure" not in rename.values():
            rename[col] = "federal_expenditure"
        elif "admin" in cl and "administrative_cost" not in rename.values():
            rename[col] = "administrative_cost"
        elif "avg" in cl and "avg_benefit_per_household" not in rename.values():
            rename[col] = "avg_benefit_per_household"
    df = df.rename(columns=rename)

    for col in SNAP_NAP_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[SNAP_NAP_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download USDA FNS NAP nutrition assistance data for PR")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nSNAP/NAP: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
