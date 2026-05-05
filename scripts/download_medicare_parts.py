"""
Download Medicare Part A (hospital insurance) and Part D (prescription drugs)
data for Puerto Rico from the CMS Data Portal.

PR receives ~$2.4B/year combined from Part A hospital payments and Part D drug
program payments. The existing download_cms.py covers Part B (physician services)
and Open Payments; this script fills the remaining Medicare coverage.

Sources tried in order:
  1. CMS Data Portal API (data.cms.gov) — search for Part D and Part A state datasets
  2. Direct CMS resource endpoints for known Part D drug spending datasets
  3. CMS Medicare geographic variation data (has state-level Part A/B/D breakdowns)

Outputs:
  data/staging/processed/pr_medicare_parts.csv

Usage:
  python3 scripts/download_medicare_parts.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

CMS_DATA_BASE = "https://data.cms.gov"
CMS_GEO_VAR_URL = "https://data.cms.gov/summary-statistics-on-use-and-payments/medicare-medicaid-spending-by-geography"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

# Known stable CMS dataset resource IDs for Part D and geographic variation
# These may change; script will fall back gracefully if they 404
CMS_KNOWN_DATASETS = [
    # Part D Drug Spending by State — CMS publishes annually
    "https://data.cms.gov/resource/6i6u-frbu.json",   # Part D spending by drug/state
    "https://data.cms.gov/resource/w96h-y9mq.json",   # Medicare Geographic Variation
    "https://data.cms.gov/resource/tbcw-ytz8.json",   # Medicare Part D state summary
]

MEDICARE_PARTS_COLUMNS = [
    "calendar_year",
    "program_part",
    "provider_or_drug_name",
    "total_beneficiaries",
    "total_claims",
    "total_payments",
    "avg_payment_per_claim",
    "state",
    "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR Medicare research)",
        "Accept": "application/json",
    })
    return s


def _get_json(session: requests.Session, url: str, params: dict, logger) -> list | dict | None:
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


def _fetch_cms_catalog(session: requests.Session, logger) -> list[str]:
    """Search CMS data catalog for Part A and Part D datasets."""
    resource_urls = []
    try:
        catalog_url = f"{CMS_DATA_BASE}/data.json"
        data = _get_json(session, catalog_url, {}, logger)
        if not data:
            return resource_urls

        datasets = data.get("dataset", []) if isinstance(data, dict) else []
        for ds in datasets:
            title = str(ds.get("title", "")).lower()
            desc = str(ds.get("description", "")).lower()
            if any(kw in title or kw in desc for kw in ["part d", "part a", "geographic variation", "drug spending"]):
                for dist in ds.get("distribution", []):
                    url = dist.get("downloadURL", dist.get("accessURL", ""))
                    if url and (".json" in url or "resource" in url):
                        resource_urls.append(url)

        logger.info(f"  Found {len(resource_urls)} Part A/D resource URLs in CMS catalog")
    except Exception as e:
        logger.warning(f"  CMS catalog search failed: {e}")
    return resource_urls


def _fetch_resource(session: requests.Session, url: str, pr_filters: list[str], logger) -> list[dict]:
    """Paginate a CMS Socrata resource endpoint filtering for PR."""
    rows = []
    limit = 1000
    offset = 0

    # Build PR filter
    filter_clause = " OR ".join(f"state='{f}'" for f in pr_filters)

    while True:
        params = {
            "$limit": limit,
            "$offset": offset,
        }
        if filter_clause:
            params["$where"] = filter_clause

        data = _get_json(session, url, params, logger)
        if not data or not isinstance(data, list):
            break

        rows.extend(data)
        if len(data) < limit:
            break
        offset += limit

    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_medicare_parts.csv"

    logger = setup_logging("download_medicare_parts")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_records: list[dict] = []
    pr_filters = ["PR", "Puerto Rico"]

    # Try known stable endpoints first
    logger.info("  Trying known CMS Part D/A endpoints...")
    for url in CMS_KNOWN_DATASETS:
        records = _fetch_resource(session, url, pr_filters, logger)
        if records:
            logger.info(f"  {url.split('/')[-1]}: {len(records):,} PR records")
            for r in records:
                r["source_doc"] = url
            all_records.extend(records)

    # Try catalog discovery
    if not all_records:
        logger.info("  Searching CMS data catalog for Part A/D datasets...")
        resource_urls = _fetch_cms_catalog(session, logger)
        for url in resource_urls[:10]:
            records = _fetch_resource(session, url, pr_filters, logger)
            if records:
                logger.info(f"  Catalog resource: {len(records):,} PR records")
                for r in records:
                    r["source_doc"] = url
                all_records.extend(records)
                if len(all_records) > 5000:
                    break

    session.close()

    if not all_records:
        logger.warning(
            "  No Medicare Part A/D data retrieved. Writing empty schema.\n"
            "  Manual alternative: download from\n"
            f"  {CMS_GEO_VAR_URL}"
        )
        pd.DataFrame(columns=MEDICARE_PARTS_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.json_normalize(all_records)

    # Flexible column mapping
    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_").replace("-", "_")
        if ("year" in cl) and "calendar_year" not in rename.values():
            rename[col] = "calendar_year"
        elif "part" in cl and "program_part" not in rename.values():
            rename[col] = "program_part"
        elif ("drug" in cl or "provider" in cl) and "name" in cl and "provider_or_drug_name" not in rename.values():
            rename[col] = "provider_or_drug_name"
        elif "beneficiar" in cl and "total_beneficiaries" not in rename.values():
            rename[col] = "total_beneficiaries"
        elif "claim" in cl and "total" in cl and "total_claims" not in rename.values():
            rename[col] = "total_claims"
        elif "payment" in cl and "total" in cl and "total_payments" not in rename.values():
            rename[col] = "total_payments"
        elif "avg" in cl and "payment" in cl and "avg_payment_per_claim" not in rename.values():
            rename[col] = "avg_payment_per_claim"
        elif col.lower() in ("state", "state_cd", "state_code") and "state" not in rename.values():
            rename[col] = "state"

    df = df.rename(columns=rename)
    df["state"] = df.get("state", "PR")
    df["state"] = df["state"].fillna("PR")

    for col in MEDICARE_PARTS_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    df = df[MEDICARE_PARTS_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")

    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR Medicare Part A + D data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nMedicare Part A/D: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
