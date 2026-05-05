"""
Download FCC Universal Service Fund (USF) disbursements for Puerto Rico.

The FCC USF has four programs with significant PR presence:
  - E-Rate: schools and libraries (~$60-80M/year for PR)
  - Rural Health Care: telehealth for PR hospitals and clinics
  - Connect America Fund (CAF/RDOF): broadband to rural PR
  - Lifeline: phone/broadband subsidies for low-income PR households

USAC (Universal Service Administrative Company) administers all four.

Sources tried in order:
  1. USAC open data API (opendata.usac.org) — primary structured data source
  2. FCC Open Data portal (opendata.fcc.gov) — CKAN-style API
  3. FCC mapping data downloads — program-level PR data files

Output:
  data/staging/processed/pr_fcc_usf.csv

Usage:
  python3 scripts/download_fcc.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

USAC_OPENDATA_BASE = "https://opendata.usac.org"
FCC_OPENDATA_BASE = "https://opendata.fcc.gov"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

FCC_COLUMNS = [
    "program_year", "program_type",
    "recipient_name", "recipient_normalized",
    "city", "state",
    "funding_amount", "category",
    "application_id", "source_doc",
]

# Known USAC open data dataset identifiers (Socrata)
USAC_DATASETS = [
    # E-Rate commitments by state
    ("https://opendata.usac.org/resource/6bcd-x6d5.json", "E-Rate", "state_name"),
    # Rural Health Care
    ("https://opendata.usac.org/resource/9w7a-4kjt.json", "Rural Health Care", "state"),
    # High Cost (CAF)
    ("https://opendata.usac.org/resource/4cem-5bfr.json", "High Cost", "state"),
    # Lifeline
    ("https://opendata.usac.org/resource/rfsp-ifce.json", "Lifeline", "state"),
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR FCC USF telecom subsidy research)",
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


def _normalize_name(name: str) -> str:
    import re
    if not name:
        return ""
    n = re.sub(r"[^\w\s]", " ", name.upper())
    n = re.sub(r"\s+", " ", n).strip()
    suffixes = {"INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "THE", "OF"}
    tokens = n.split()
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _fetch_usac_dataset(session: requests.Session, url: str, program_type: str,
                         state_field: str, logger) -> list[dict]:
    rows = []
    limit = 1000
    offset = 0
    pr_values = ["PR", "Puerto Rico", "PUERTO RICO"]

    for pr_val in pr_values[:1]:
        offset = 0
        while True:
            params = {
                "$limit": limit,
                "$offset": offset,
                "$where": f"{state_field}='PR' OR {state_field}='Puerto Rico'",
            }
            data = _get_json(session, url, params, logger)
            if not data or not isinstance(data, list):
                break
            rows.extend(data)
            if len(data) < limit:
                break
            offset += limit

        if not rows:
            # Try without where clause, filter client-side
            offset = 0
            while offset < 50000:
                params = {"$limit": limit, "$offset": offset}
                data = _get_json(session, url, params, logger)
                if not data or not isinstance(data, list):
                    break
                pr_rows = [r for r in data
                           if any(str(r.get(state_field, "")).upper() in ("PR", "PUERTO RICO")
                                  for _ in [1])]
                rows.extend(pr_rows)
                if len(data) < limit:
                    break
                offset += limit
                if len(rows) > 5000:
                    break

    for r in rows:
        r["_program_type"] = program_type
        r["source_doc"] = url

    if rows:
        logger.info(f"  {program_type}: {len(rows):,} PR records")
    return rows


def _fetch_fcc_opendata(session: requests.Session, logger) -> list[dict]:
    rows = []
    try:
        search_url = f"{FCC_OPENDATA_BASE}/api/views"
        data = _get_json(session, search_url, {"limit": 100}, logger)
        if not data or not isinstance(data, list):
            return rows
        for view in data[:20]:
            name = str(view.get("name", "")).lower()
            if not any(kw in name for kw in ["erate", "e-rate", "usf", "universal service", "usac", "lifeline"]):
                continue
            view_id = view.get("id", "")
            if not view_id:
                continue
            resource_url = f"{FCC_OPENDATA_BASE}/resource/{view_id}.json"
            params = {
                "$limit": 1000,
                "$where": "state='PR' OR state='Puerto Rico'",
            }
            vdata = _get_json(session, resource_url, params, logger)
            if vdata and isinstance(vdata, list):
                for r in vdata:
                    r["_program_type"] = "FCC_OpenData"
                    r["source_doc"] = resource_url
                rows.extend(vdata)
                logger.info(f"  FCC OpenData view {view_id}: {len(vdata)} PR records")
    except Exception as e:
        logger.warning(f"  FCC Open Data fetch failed: {e}")
    return rows


def _normalize_records(all_rows: list[dict], logger) -> pd.DataFrame:
    if not all_rows:
        return pd.DataFrame(columns=FCC_COLUMNS)

    df = pd.json_normalize(all_rows)

    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_").replace("-", "_")
        if ("year" in cl or "funding_year" in cl or "program_year" in cl) and "program_year" not in rename.values():
            rename[col] = "program_year"
        elif "_program_type" == col and "program_type" not in rename.values():
            rename[col] = "program_type"
        elif ("applicant" in cl or "recipient" in cl or "entity" in cl or "school" in cl
              or "org" in cl) and "name" in cl and "recipient_name" not in rename.values():
            rename[col] = "recipient_name"
        elif ("city" in cl or "urban" in cl) and "city" not in rename.values():
            rename[col] = "city"
        elif col.lower() in ("state", "state_name", "state_abbreviation") and "state" not in rename.values():
            rename[col] = "state"
        elif ("amount" in cl or "commitment" in cl or "disbursement" in cl or "funding" in cl
              ) and "funding_amount" not in rename.values():
            rename[col] = "funding_amount"
        elif ("category" in cl or "service" in cl) and "category" not in rename.values():
            rename[col] = "category"
        elif ("application" in cl or "frn" in cl or "ben" in cl) and "application_id" not in rename.values():
            rename[col] = "application_id"

    df = df.rename(columns=rename)

    if "recipient_name" in df.columns:
        df["recipient_normalized"] = df["recipient_name"].apply(
            lambda x: _normalize_name(str(x or ""))
        )
    else:
        df["recipient_normalized"] = ""

    for col in FCC_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    logger.info(f"  Normalized {len(df):,} FCC/USF records")
    return df[FCC_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_fcc_usf.csv"

    logger = setup_logging("download_fcc")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    logger.info("  Fetching USAC open data for E-Rate, Rural Health Care, High Cost, Lifeline...")
    for url, program_type, state_field in USAC_DATASETS:
        dataset_rows = _fetch_usac_dataset(session, url, program_type, state_field, logger)
        all_rows.extend(dataset_rows)

    if not all_rows:
        logger.info("  Trying FCC Open Data portal...")
        fcc_rows = _fetch_fcc_opendata(session, logger)
        all_rows.extend(fcc_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No FCC/USF data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://opendata.usac.org"
        )
        pd.DataFrame(columns=FCC_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = _normalize_records(all_rows, logger)
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download FCC USF telecom subsidy data for PR")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFCC/USF: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
