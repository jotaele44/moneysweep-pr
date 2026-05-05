"""
Download Social Security Administration benefit data for Puerto Rico.

PR receives ~$2.5-3B/year in OASDI (retirement/survivors/disability) and SSI
(Supplemental Security Income) benefits. This captures beneficiary counts and
total payment amounts by program type.

Sources tried in order:
  1. data.ssa.gov CKAN API — SSA Open Data portal
  2. SSA OASDI state Excel files — annual state-level tables
  3. SSA SSI state Excel files — annual state supplement tables

Outputs:
  data/staging/processed/pr_ssa_benefits.csv

Usage:
  python3 scripts/download_ssa.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

SSA_OPEN_DATA_BASE = "https://data.ssa.gov"
SSA_OASDI_BASE = "https://www.ssa.gov/policy/docs/statcomps/oasdi_sc"
SSA_SSI_BASE = "https://www.ssa.gov/policy/docs/statcomps/ssi_sc"

PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [5, 15, 30]

# Fiscal years to attempt for annual state tables
YEARS_TO_FETCH = list(range(2010, 2025))

SSA_COLUMNS = [
    "calendar_year", "month",
    "program_type",
    "beneficiary_count",
    "total_payments",
    "avg_monthly_benefit",
    "retired_workers_count",
    "disabled_workers_count",
    "survivors_count",
    "source_doc",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR SSA benefits research)",
        "Accept": "application/json, text/html",
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


def _fetch_ssa_open_data(session: requests.Session, logger) -> list[dict]:
    """Query SSA Open Data CKAN API for PR benefit data."""
    rows = []
    try:
        search_url = f"{SSA_OPEN_DATA_BASE}/api/views"
        data = _get(session, search_url, {"limit": 100}, logger)
        if not data:
            return rows

        items = data if isinstance(data, list) else []
        pr_views = [
            v for v in items
            if isinstance(v, dict) and any(
                "state" in str(v.get(f, "")).lower() or "benefit" in str(v.get(f, "")).lower()
                for f in ["name", "description"]
            )
        ]
        logger.info(f"  Found {len(pr_views)} candidate SSA datasets")

        for view in pr_views[:5]:
            view_id = view.get("id", "")
            if not view_id:
                continue
            data_url = f"{SSA_OPEN_DATA_BASE}/api/views/{view_id}/rows.json"
            data = _get(session, data_url, {}, logger)
            if not data:
                continue
            cols = [c.get("fieldName", "") for c in data.get("meta", {}).get("view", {}).get("columns", [])]
            raw_rows = data.get("data", [])
            for r in raw_rows:
                row_dict = dict(zip(cols, r))
                state_val = str(row_dict.get("state", row_dict.get("state_name", ""))).upper()
                if state_val in ("PR", "PUERTO RICO"):
                    rows.append(row_dict)
            if rows:
                logger.info(f"  SSA Open Data view {view_id}: {len(rows)} PR rows so far")
    except Exception as e:
        logger.warning(f"  SSA Open Data API failed: {e}")
    return rows


def _fetch_ssa_state_tables(session: requests.Session, logger) -> list[dict]:
    """Download SSA state-level annual Excel/HTML tables for OASDI and SSI."""
    rows = []

    for base_url, program in [(SSA_OASDI_BASE, "OASDI"), (SSA_SSI_BASE, "SSI")]:
        for year in YEARS_TO_FETCH:
            # Try common filename patterns
            candidates = [
                f"{base_url}/{year}/pr.xlsx",
                f"{base_url}/{year}/pr.xls",
                f"{base_url}/{year}/table01.xlsx",
                f"{base_url}/{year}/t01.xlsx",
            ]
            for url in candidates:
                try:
                    resp = session.get(url, timeout=30)
                    if resp.status_code != 200:
                        continue
                    content_type = resp.headers.get("content-type", "")
                    if "excel" in content_type or "spreadsheet" in content_type or url.endswith((".xlsx", ".xls")):
                        df = pd.read_excel(pd.io.common.BytesIO(resp.content), header=None)
                    elif "html" in content_type:
                        tables = pd.read_html(resp.text)
                        df = tables[0] if tables else pd.DataFrame()
                    else:
                        continue

                    # Look for PR data in the table
                    for col in df.columns:
                        mask = df[col].astype(str).str.upper().isin(["PR", "PUERTO RICO"])
                        if mask.sum() > 0:
                            pr_df = df[mask].copy()
                            pr_df["calendar_year"] = year
                            pr_df["program_type"] = program
                            pr_df["source_doc"] = url
                            rows.extend(pr_df.to_dict("records"))
                            logger.info(f"  {program} {year}: {mask.sum()} PR rows from {url.split('/')[-1]}")
                            break
                    break
                except Exception:
                    continue
            time.sleep(PAGE_SLEEP)

    return rows


def _normalize_records(records: list[dict], logger) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=SSA_COLUMNS)

    df = pd.json_normalize(records)

    rename = {}
    for col in df.columns:
        cl = col.lower().replace(" ", "_").replace("-", "_")
        if ("year" in cl or cl == "fy") and "calendar_year" not in rename.values():
            rename[col] = "calendar_year"
        elif "month" in cl and "month" not in rename.values():
            rename[col] = "month"
        elif "program" in cl and "type" in cl and "program_type" not in rename.values():
            rename[col] = "program_type"
        elif "beneficiar" in cl and "count" in cl:
            rename[col] = "beneficiary_count"
        elif "total" in cl and "payment" in cl:
            rename[col] = "total_payments"
        elif "avg" in cl and "benefit" in cl:
            rename[col] = "avg_monthly_benefit"
        elif "retired" in cl:
            rename[col] = "retired_workers_count"
        elif "disabled" in cl or "disability" in cl:
            rename[col] = "disabled_workers_count"
        elif "survivor" in cl:
            rename[col] = "survivors_count"
        elif "source" in cl and "doc" in cl:
            rename[col] = "source_doc"

    df = df.rename(columns=rename)

    for col in SSA_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    logger.info(f"  Normalized {len(df):,} SSA records")
    return df[SSA_COLUMNS]


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root = Path(root)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "pr_ssa_benefits.csv"

    logger = setup_logging("download_ssa")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    session = _session()
    all_records: list[dict] = []

    logger.info("  Querying SSA Open Data portal...")
    api_records = _fetch_ssa_open_data(session, logger)
    all_records.extend(api_records)

    if not all_records:
        logger.info("  Trying SSA state-level annual tables...")
        table_records = _fetch_ssa_state_tables(session, logger)
        all_records.extend(table_records)

    session.close()

    if not all_records:
        logger.warning(
            "  No SSA data retrieved. Writing empty schema.\n"
            "  Manual alternative: download state tables from\n"
            f"  {SSA_OASDI_BASE} and {SSA_SSI_BASE}"
        )
        pd.DataFrame(columns=SSA_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    df = _normalize_records(all_records, logger)
    df.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(df):,} rows)")

    return {"rows": len(df), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR SSA OASDI/SSI benefit data")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nSSA benefits: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
