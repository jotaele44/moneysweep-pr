"""
Download CMS CHIP (Children's Health Insurance Program) data for Puerto Rico.

PR CHIP is administered under CMS, ~$100-200M/yr, separate from Medicaid FMAP.
PR receives an enhanced FMAP rate for CHIP as a territory.

Sources tried in order:
  1. data.medicaid.gov CKAN metastore — filter for CHIP datasets, PR state
  2. CMS CHIP expenditure reports API
  3. data.gov CKAN search

Output:
  data/staging/processed/pr_chip.csv

Usage:
  python3 scripts/download_chip.py [--force]
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

CHIP_COLUMNS = [
    "fiscal_year", "quarter", "enrollment_count",
    "federal_expenditure", "state_expenditure", "total_expenditure",
    "fmap_rate", "source_doc",
]

MEDICAID_GOV_API = "https://data.medicaid.gov/api/1/metastore/schemas/dataset/items"
CMS_CHIP_API = "https://data.medicaid.gov/api/1/datastore/query"
DATA_GOV_SEARCH = "https://catalog.data.gov/api/3/action/package_search"


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (CMS CHIP PR research)",
        "Accept": "application/json",
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


def _fetch_medicaid_gov(session, logger) -> list[dict]:
    rows = []
    logger.info("  Searching data.medicaid.gov for CHIP datasets...")
    resp = _get(session, MEDICAID_GOV_API, {"%5B%5D": "keyword=chip"}, logger)
    if not resp:
        return rows
    try:
        datasets = resp.json()
    except Exception:
        return rows

    chip_ids = []
    for ds in datasets:
        title = str(ds.get("title", "")).lower()
        if "chip" in title or "children" in title:
            for dist in ds.get("distribution", []):
                if dist.get("mediaType") in ("text/csv", "application/json"):
                    chip_ids.append((ds.get("identifier", ""), dist.get("identifier", "")))

    for ds_id, dist_id in chip_ids[:5]:
        logger.info(f"  Querying CHIP dataset {ds_id}...")
        query_url = f"{CMS_CHIP_API}/{dist_id}"
        offset = 0
        limit = 500
        while True:
            params = {
                "conditions[0][property]": "state",
                "conditions[0][value]": "PR",
                "conditions[0][operator]": "=",
                "limit": limit,
                "offset": offset,
            }
            resp2 = _get(session, query_url, params, logger)
            if not resp2:
                break
            try:
                data = resp2.json()
            except Exception:
                break
            results = data.get("results", data.get("data", []))
            if not results:
                break
            for r in results:
                rows.append({
                    "fiscal_year": str(r.get("fiscal_year", r.get("year", r.get("fy", "")))),
                    "quarter": str(r.get("quarter", r.get("reporting_quarter", ""))),
                    "enrollment_count": str(r.get("enrollment", r.get("enrollees", r.get("chip_enrollment", "")))),
                    "federal_expenditure": str(r.get("federal_expenditure", r.get("federal_share", r.get("chip_federal_expenditure", "")))),
                    "state_expenditure": str(r.get("state_expenditure", r.get("state_share", ""))),
                    "total_expenditure": str(r.get("total_expenditure", r.get("total_computable", ""))),
                    "fmap_rate": str(r.get("fmap_rate", r.get("e_fmap", r.get("chip_fmap", "")))),
                    "source_doc": query_url,
                })
            if len(results) < limit:
                break
            offset += limit
            time.sleep(PAGE_SLEEP)
        if rows:
            break
    return rows


def _fetch_data_gov(session, logger) -> list[dict]:
    rows = []
    logger.info("  Searching data.gov for CHIP Puerto Rico datasets...")
    params = {"q": "CHIP children health insurance Puerto Rico", "rows": 10}
    resp = _get(session, DATA_GOV_SEARCH, params, logger)
    if not resp:
        return rows
    try:
        result = resp.json()
    except Exception:
        return rows

    for pkg in result.get("result", {}).get("results", []):
        for resource in pkg.get("resources", []):
            if resource.get("format", "").upper() in ("CSV", "JSON"):
                url = resource.get("url", "")
                if not url:
                    continue
                resp2 = _get(session, url, {}, logger)
                if not resp2:
                    continue
                try:
                    if url.endswith(".csv"):
                        df = pd.read_csv(
                            pd.io.common.StringIO(resp2.text),
                            dtype=str, low_memory=False
                        )
                    else:
                        data = resp2.json()
                        df = pd.json_normalize(data if isinstance(data, list) else [])
                    state_cols = [c for c in df.columns if "state" in c.lower()]
                    if state_cols:
                        df = df[df[state_cols[0]].str.upper().str.contains("PR|PUERTO RICO", na=False)]
                    if df.empty:
                        continue
                    for _, r in df.iterrows():
                        r_dict = r.to_dict()
                        rows.append({
                            "fiscal_year": str(r_dict.get("fiscal_year", r_dict.get("year", ""))),
                            "quarter": str(r_dict.get("quarter", "")),
                            "enrollment_count": str(r_dict.get("enrollment", r_dict.get("enrollees", ""))),
                            "federal_expenditure": str(r_dict.get("federal_expenditure", r_dict.get("federal_share", ""))),
                            "state_expenditure": str(r_dict.get("state_expenditure", "")),
                            "total_expenditure": str(r_dict.get("total_expenditure", "")),
                            "fmap_rate": str(r_dict.get("fmap_rate", r_dict.get("e_fmap", ""))),
                            "source_doc": url,
                        })
                    if rows:
                        logger.info(f"  data.gov: {len(rows)} PR CHIP rows from {url[:60]}")
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
    out_path = out_dir / "pr_chip.csv"

    logger = setup_logging("download_chip")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    medicaid_rows = _fetch_medicaid_gov(session, logger)
    all_rows.extend(medicaid_rows)

    if not all_rows:
        datagov_rows = _fetch_data_gov(session, logger)
        all_rows.extend(datagov_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No CHIP data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://www.medicaid.gov/chip/chip-program-information/index.html"
        )
        pd.DataFrame(columns=CHIP_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in CHIP_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[CHIP_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download CMS CHIP data for Puerto Rico")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nCHIP: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
