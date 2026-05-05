"""
Download CMS Medicare Advantage plan payments to Puerto Rico.

CMS pays MA plans ~$2-3B/yr in PR; fee-for-service is covered by
download_medicare_parts.py, but MA capitation payments are separate.

Sources tried in order:
  1. CMS MA Landscape Excel files (annual, by contract year)
  2. CMS data.cms.gov Socrata — MA enrollment datasets filtered to PR
  3. CMS monthly enrollment API

Output:
  data/staging/processed/pr_medicare_advantage.csv

Usage:
  python3 scripts/download_medicare_advantage.py [--force]
"""

import argparse
import io
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

MA_COLUMNS = [
    "contract_year", "plan_id", "plan_name", "organization_name",
    "organization_normalized", "plan_type", "enrollment_count",
    "capitation_rate", "total_payment", "county", "state", "source_doc",
]

CMS_SOCRATA_ENDPOINTS = [
    "https://data.cms.gov/resource/qksd-9k7j.json",
    "https://data.cms.gov/resource/nu5k-459e.json",
    "https://data.cms.gov/resource/r9ta-rabe.json",
]

CMS_LANDSCAPE_BASE = (
    "https://www.cms.gov/Medicare/Health-Plans/MedicareAdvtgSpecRateStats/Landscape"
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (CMS Medicare Advantage PR research)",
        "Accept": "application/json, text/html",
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


def _normalize_name(name: str) -> str:
    if not name:
        return ""
    n = re.sub(r"[^\w\s]", " ", str(name).upper())
    n = re.sub(r"\s+", " ", n).strip()
    suffixes = {"INC", "LLC", "LLP", "CORP", "CO", "LTD", "LP", "THE", "OF", "HEALTH", "PLAN", "PLANS"}
    tokens = n.split()
    while tokens and tokens[-1] in suffixes:
        tokens.pop()
    return " ".join(tokens)


def _fetch_socrata(session, logger) -> list[dict]:
    rows = []
    for endpoint in CMS_SOCRATA_ENDPOINTS:
        logger.info(f"  Trying CMS Socrata: {endpoint}")
        offset = 0
        limit = 5000
        while True:
            params = {
                "$where": "state_code='PR' OR state='PR' OR state='Puerto Rico'",
                "$limit": limit,
                "$offset": offset,
            }
            resp = _get(session, endpoint, params, logger)
            if not resp:
                break
            try:
                data = resp.json()
            except Exception:
                break
            if not data:
                break
            for r in data:
                org = str(r.get("organization_name", r.get("organization_marketing_name", r.get("plan_name", ""))))
                rows.append({
                    "contract_year": str(r.get("contract_year", r.get("year", ""))),
                    "plan_id": str(r.get("contract_id", r.get("plan_id", r.get("h_number", "")))),
                    "plan_name": str(r.get("plan_name", r.get("plan_marketing_name", ""))),
                    "organization_name": org,
                    "organization_normalized": _normalize_name(org),
                    "plan_type": str(r.get("plan_type", r.get("organization_type", ""))),
                    "enrollment_count": str(r.get("enrollment", r.get("enrolled", r.get("beneficiaries", "")))),
                    "capitation_rate": str(r.get("capitation_rate", r.get("payment_rate", ""))),
                    "total_payment": str(r.get("total_payment", r.get("payment_amount", ""))),
                    "county": str(r.get("county", r.get("county_name", ""))),
                    "state": "PR",
                    "source_doc": endpoint,
                })
            if len(data) < limit:
                break
            offset += limit
            time.sleep(PAGE_SLEEP)
        if rows:
            logger.info(f"  CMS Socrata: {len(rows)} rows")
            return rows
    return rows


def _fetch_landscape(session, logger) -> list[dict]:
    rows = []
    current_year = 2025
    for year in range(current_year, 2018, -1):
        url = f"{CMS_LANDSCAPE_BASE}/Downloads/landscape_{year}.xlsx"
        logger.info(f"  Trying CMS Landscape {year}: {url}")
        resp = _get(session, url, {}, logger)
        if not resp or not resp.content:
            url2 = f"{CMS_LANDSCAPE_BASE}/Downloads/landscape-{year}.xlsx"
            resp = _get(session, url2, {}, logger)
        if not resp or not resp.content:
            continue
        try:
            df = pd.read_excel(io.BytesIO(resp.content), dtype=str)
        except Exception as e:
            logger.warning(f"  Could not parse landscape {year}: {e}")
            continue
        state_cols = [c for c in df.columns if "state" in c.lower()]
        if not state_cols:
            continue
        pr_mask = df[state_cols[0]].str.upper().str.contains("PR|PUERTO RICO", na=False)
        df_pr = df[pr_mask].copy()
        if df_pr.empty:
            continue
        col_map = {
            "plan_id": ["Contract ID", "Contract Number", "H Number"],
            "plan_name": ["Plan Name", "Plan Marketing Name"],
            "organization_name": ["Organization Name", "Organization Marketing Name"],
            "plan_type": ["Plan Type", "Organization Type"],
            "enrollment_count": ["Enrollment", "Enrolled", "Beneficiaries"],
            "capitation_rate": ["Capitation Rate", "Payment Rate", "Benchmark Premium"],
            "county": ["County", "County Name"],
        }
        mapped: dict[str, str] = {}
        for target, candidates in col_map.items():
            for c in candidates:
                if c in df_pr.columns:
                    mapped[target] = c
                    break
        for _, r in df_pr.iterrows():
            org = str(r.get(mapped.get("organization_name", ""), ""))
            rows.append({
                "contract_year": str(year),
                "plan_id": str(r.get(mapped.get("plan_id", ""), "")),
                "plan_name": str(r.get(mapped.get("plan_name", ""), "")),
                "organization_name": org,
                "organization_normalized": _normalize_name(org),
                "plan_type": str(r.get(mapped.get("plan_type", ""), "")),
                "enrollment_count": str(r.get(mapped.get("enrollment_count", ""), "")),
                "capitation_rate": str(r.get(mapped.get("capitation_rate", ""), "")),
                "total_payment": "",
                "county": str(r.get(mapped.get("county", ""), "")),
                "state": "PR",
                "source_doc": url,
            })
        logger.info(f"  Landscape {year}: {len(df_pr)} PR rows")
        if rows:
            break
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_medicare_advantage.csv"

    logger = setup_logging("download_medicare_advantage")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_rows: list[dict] = []

    logger.info("  Trying CMS Socrata endpoints for Medicare Advantage PR data...")
    socrata_rows = _fetch_socrata(session, logger)
    all_rows.extend(socrata_rows)

    if not all_rows:
        logger.info("  Trying CMS MA Landscape Excel files...")
        landscape_rows = _fetch_landscape(session, logger)
        all_rows.extend(landscape_rows)

    session.close()

    if not all_rows:
        logger.warning(
            "  No Medicare Advantage data retrieved. Writing empty schema.\n"
            "  Manual alternative: https://www.cms.gov/Medicare/Health-Plans/"
            "MedicareAdvtgSpecRateStats/Landscape"
        )
        pd.DataFrame(columns=MA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = pd.DataFrame(all_rows)
    for col in MA_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[MA_COLUMNS]
    if "plan_id" in df.columns and "contract_year" in df.columns:
        df = df.drop_duplicates(subset=["plan_id", "contract_year"], keep="first")
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download CMS Medicare Advantage PR plan data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nMedicare Advantage: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
