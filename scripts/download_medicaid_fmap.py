"""
Download Puerto Rico Medicaid FMAP rates and CMS-64 expenditure data.

PR's FMAP rate is ~83% (among the highest in the US due to its territory status),
meaning the federal government pays ~83 cents of every Medicaid dollar spent in PR.
Total federal Medicaid contribution to PR is ~$3-4B/year.

Sources tried in order:
  1. data.medicaid.gov CKAN API — PR-filtered expenditure datasets
  2. CMS FMAP rate table HTML — annual FMAP percentages
  3. CMS-64 quarterly expenditure report HTML index

Outputs:
  data/staging/processed/pr_medicaid_fmap.csv

Usage:
  python3 scripts/download_medicaid_fmap.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

MEDICAID_DATA_BASE = "https://data.medicaid.gov"
FMAP_PAGE_URL = "https://www.medicaid.gov/medicaid/finance/state-expenditure-reporting/fmap/index.html"
CMS64_INDEX_URL = "https://www.medicaid.gov/medicaid/finance/state-expenditure-reporting/expenditure-reports/index.html"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

MEDICAID_COLUMNS = [
    "fiscal_year", "quarter",
    "fmap_rate",
    "total_expenditure",
    "federal_share",
    "state_share",
    "dsh_allotment",
    "managed_care_expenditure",
    "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR Medicaid research)",
        "Accept": "application/json",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code} for {url} — skipping")
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
                logger.error(f"  All {MAX_RETRIES} attempts failed for {url}: {exc}")
    return None


def _fetch_medicaid_data_api(session: requests.Session, logger) -> list[dict]:
    """Try data.medicaid.gov CKAN-style API for PR expenditure datasets."""
    rows = []
    try:
        # Search for datasets related to Puerto Rico expenditures
        search_url = f"{MEDICAID_DATA_BASE}/api/1/metastore/schemas/dataset/items"
        data = _get(session, search_url, {"limit": 100}, logger)
        if not data:
            return rows

        items = data if isinstance(data, list) else data.get("data", [])
        pr_datasets = [
            d for d in items
            if isinstance(d, dict) and any(
                "puerto rico" in str(d.get(f, "")).lower() or "expenditure" in str(d.get(f, "")).lower()
                for f in ["title", "description", "keyword"]
            )
        ]
        logger.info(f"  Found {len(pr_datasets)} potentially relevant datasets on data.medicaid.gov")

        for ds in pr_datasets[:5]:
            dist = ds.get("distribution", [])
            for d in (dist if isinstance(dist, list) else []):
                dl_url = d.get("downloadURL", "")
                if dl_url and dl_url.endswith(".csv"):
                    try:
                        df = pd.read_csv(dl_url, low_memory=False)
                        # Filter for PR rows
                        for col in df.columns:
                            if "state" in col.lower() or "territory" in col.lower():
                                mask = df[col].astype(str).str.upper().isin(["PR", "PUERTO RICO"])
                                if mask.sum() > 0:
                                    rows.extend(df[mask].to_dict("records"))
                                    logger.info(f"  {dl_url.split('/')[-1]}: {mask.sum()} PR rows")
                                    break
                    except Exception as e:
                        logger.debug(f"  Could not read {dl_url}: {e}")
                time.sleep(PAGE_SLEEP)
    except Exception as e:
        logger.warning(f"  data.medicaid.gov API failed: {e}")
    return rows


def _fetch_fmap_rates(session: requests.Session, logger) -> list[dict]:
    """Scrape FMAP rate table from Medicaid.gov."""
    rows = []
    try:
        resp = session.get(FMAP_PAGE_URL, timeout=60)
        if resp.status_code != 200:
            logger.warning(f"  FMAP page returned HTTP {resp.status_code}")
            return rows

        try:
            tables = pd.read_html(resp.text)
        except Exception:
            logger.warning("  No HTML tables found on FMAP page")
            return rows

        for tbl in tables:
            # Look for PR row in any table
            for col in tbl.columns:
                mask = tbl[col].astype(str).str.upper().isin(["PR", "PUERTO RICO"])
                if mask.sum() > 0:
                    pr_rows = tbl[mask].copy()
                    pr_rows["source_doc"] = FMAP_PAGE_URL
                    rows.extend(pr_rows.to_dict("records"))
                    logger.info(f"  FMAP table: {mask.sum()} PR rows")
                    break
    except Exception as e:
        logger.warning(f"  FMAP page scrape failed: {e}")
    return rows


def _normalize_records(records: list[dict], logger) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=MEDICAID_COLUMNS)

    df = pd.json_normalize(records)

    # Flexible column mapping
    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_").replace("-", "_")
        if "fiscal_year" in cl or "fy" == cl:
            rename[col] = "fiscal_year"
        elif "quarter" in cl and "quarter" not in rename.values():
            rename[col] = "quarter"
        elif "fmap" in cl and "rate" in cl:
            rename[col] = "fmap_rate"
        elif "total" in cl and "expenditure" in cl and "total_expenditure" not in rename.values():
            rename[col] = "total_expenditure"
        elif "federal" in cl and "share" in cl:
            rename[col] = "federal_share"
        elif "state" in cl and "share" in cl:
            rename[col] = "state_share"
        elif "dsh" in cl or "disproportionate" in cl:
            rename[col] = "dsh_allotment"
        elif "managed_care" in cl or ("managed" in cl and "care" in cl):
            rename[col] = "managed_care_expenditure"
        elif "source" in cl and "doc" in cl:
            rename[col] = "source_doc"

    df = df.rename(columns=rename)

    for col in MEDICAID_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    # Standardize fiscal_year
    if "fiscal_year" in df.columns:
        df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce").fillna(0).astype(int)

    logger.info(f"  Normalized {len(df):,} Medicaid records")
    return df[MEDICAID_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_medicaid_fmap.csv"

    logger = setup_logging("download_medicaid_fmap")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_records: list[dict] = []

    logger.info("  Fetching Medicaid FMAP rates from Medicaid.gov...")
    fmap_records = _fetch_fmap_rates(session, logger)
    all_records.extend(fmap_records)

    logger.info("  Querying data.medicaid.gov API for PR expenditure data...")
    api_records = _fetch_medicaid_data_api(session, logger)
    all_records.extend(api_records)

    session.close()

    if not all_records:
        logger.warning(
            "  No Medicaid data retrieved. Writing empty schema.\n"
            "  Manual alternative: download CMS-64 reports from\n"
            f"  {CMS64_INDEX_URL}"
        )
        pd.DataFrame(columns=MEDICAID_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = _normalize_records(all_records, logger)
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")

    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR Medicaid FMAP data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nMedicaid FMAP: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
