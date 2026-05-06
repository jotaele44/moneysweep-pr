"""
Download COR3 (Central Office for Recovery, Reconstruction and Resiliency) project
data from Puerto Rico's public recovery transparency portal (recovery.pr.gov).

COR3 is the bridge between federal FEMA PA/HMGP awards and PR government execution.
It tracks how much federal recovery money has been approved vs. actually disbursed
per project, revealing disbursement bottlenecks and delivery delays.

Outputs:
  data/staging/raw/cor3/cor3_projects_raw.json
  data/staging/processed/pr_cor3_projects.csv

Usage:
  python3 scripts/download_cor3.py
  python3 scripts/download_cor3.py --force
"""

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.build_unified_master import _normalize_name
from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.web_fetch import (
    extract_json_from_html_page,
    fetch_paginated_json,
    session_with_headers,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COR3_BASE = "https://recovery.pr.gov"

# COR3 portal loads project data via XHR — try known API patterns
COR3_ENDPOINTS = [
    "/api/projects",
    "/api/v1/projects",
    "/en/api/projects",
    "/en/transparencia/api/projects",
    "/transparency/api/projects",
]

# Fallback: CSV/JSON data exports sometimes published at these paths
COR3_DATA_EXPORTS = [
    "/files/projects_data.json",
    "/files/projects.csv",
    "/en/files/projects_data.json",
]

PAGE_SIZE    = 500
PAGE_SLEEP   = 0.5
MAX_RETRIES  = 3
RETRY_BACKOFF = [5, 15, 30]

OUTPUT_COLUMNS = [
    "project_id", "applicant_name", "applicant_normalized",
    "program", "category", "municipality",
    "total_approved", "total_disbursed", "disbursement_rate",
    "status", "last_updated",
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    return session_with_headers({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR recovery research)",
        "Referer": COR3_BASE + "/en/transparencia",
    })


# ---------------------------------------------------------------------------
# Try API endpoints
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _try_json_endpoint(session, endpoint, logger) -> list[dict]:
    """Attempt to fetch JSON project list from a COR3 API endpoint."""
    url = COR3_BASE + endpoint
    records = fetch_paginated_json(
        session,
        url,
        params={"limit": PAGE_SIZE},
        page_param="page",
        page_size_param="per_page",
        page_size=PAGE_SIZE,
        max_pages=100,
        logger=logger,
        items_keys=["data", "results", "projects", "items"],
    )
    if records:
        return records

    embedded = extract_json_from_html_page(session, url, logger=logger)
    if isinstance(embedded, list):
        return embedded
    if isinstance(embedded, dict):
        return embedded.get("data") or embedded.get("results") or embedded.get("projects") or embedded.get("items") or []
    return []


def _try_csv_export(session, path, logger) -> list[dict]:
    """Try a static CSV export path."""
    url = COR3_BASE + path
    resp = _get(session, url, {}, logger)
    if resp is None or resp.status_code >= 400:
        return []
    try:
        df = pd.read_csv(pd.io.common.BytesIO(resp.content), dtype=str)
        return df.to_dict("records")
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------

def _normalize_record(r: dict) -> dict:
    """Map raw COR3 record to canonical schema."""
    def _f(*keys):
        for k in keys:
            v = r.get(k) or r.get(k.lower()) or r.get(k.upper())
            if v is not None:
                return str(v)
        return ""

    applicant = _f("applicant_name", "applicant", "subrecipient", "name", "entity_name")
    approved  = _f("total_approved", "approved_amount", "obligated_amount", "grant_amount")
    disbursed = _f("total_disbursed", "disbursed_amount", "paid_amount", "reimbursed_amount")

    try:
        approved_f  = float(approved.replace(",", "").replace("$", "")) if approved else 0.0
    except ValueError:
        approved_f = 0.0
    try:
        disbursed_f = float(disbursed.replace(",", "").replace("$", "")) if disbursed else 0.0
    except ValueError:
        disbursed_f = 0.0

    rate = round(disbursed_f / approved_f, 4) if approved_f > 0 else 0.0

    return {
        "project_id":           _f("project_id", "id", "project_number", "dsr_id"),
        "applicant_name":       applicant,
        "applicant_normalized": _normalize_name(applicant),
        "program":              _f("program", "program_name", "fund_type", "program_type"),
        "category":             _f("category", "work_category", "project_category"),
        "municipality":         _f("municipality", "city", "location", "community"),
        "total_approved":       approved_f,
        "total_disbursed":      disbursed_f,
        "disbursement_rate":    rate,
        "status":               _f("status", "project_status", "current_status"),
        "last_updated":         _f("last_updated", "updated_at", "modified_date"),
    }


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    raw_dir  = root / "data" / "staging" / "raw" / "cor3"
    out_path = root / "data" / "staging" / "processed" / "pr_cor3_projects.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_cor3", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  COR3: {out_path.name} exists ({rows:,} rows) — skipping.")
        return {"status": "CACHED", "rows": rows}

    session = _session()
    raw_records: list[dict] = []

    # Try JSON API endpoints first
    for endpoint in COR3_ENDPOINTS:
        logger.info(f"  Trying COR3 endpoint: {endpoint}")
        records = _try_json_endpoint(session, endpoint, logger)
        if records:
            logger.info(f"  Found {len(records):,} records at {endpoint}")
            raw_records = records
            break
        logger.debug(f"    No data at {endpoint}")

    # Try static CSV exports if APIs failed
    if not raw_records:
        for path in COR3_DATA_EXPORTS:
            logger.info(f"  Trying COR3 export: {path}")
            records = _try_csv_export(session, path, logger)
            if records:
                logger.info(f"  Found {len(records):,} records at {path}")
                raw_records = records
                break

    if not raw_records:
        logger.warning(
            "  COR3 API returned no data. The portal may require JavaScript rendering.\n"
            "  Manual export: visit https://recovery.pr.gov/en/transparencia and download CSV."
        )
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    # Save raw
    raw_path = raw_dir / "cor3_projects_raw.json"
    raw_path.write_text(json.dumps(raw_records, ensure_ascii=False, indent=2))
    logger.info(f"  Raw data saved: {raw_path.name}")

    # Normalize
    normalized = [_normalize_record(r) for r in raw_records]
    df = pd.DataFrame(normalized, columns=OUTPUT_COLUMNS)
    df = df.drop_duplicates(subset=["project_id"]).sort_values(
        "total_approved", ascending=False
    )
    df.to_csv(out_path, index=False)

    n = len(df)
    total_approved  = df["total_approved"].sum()
    total_disbursed = df["total_disbursed"].sum()
    avg_rate = round(total_disbursed / total_approved, 3) if total_approved > 0 else 0

    logger.info(f"  COR3: {n:,} projects → {out_path.name}")
    logger.info(f"  Approved: ${total_approved:,.0f}, Disbursed: ${total_disbursed:,.0f} ({avg_rate:.1%})")

    return {
        "status": "OK", "rows": n,
        "total_approved": total_approved,
        "total_disbursed": total_disbursed,
        "avg_disbursement_rate": avg_rate,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download COR3 recovery project data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = run(force=args.force)
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
