"""Download FSRS (Federal Subaward Reporting System) subcontract data for Puerto Rico.

FSRS.gov has no public API and requires manual web-browser export.  As a
functionally equivalent alternative this script fetches the same subaward
records through the USAspending spending_by_award endpoint (which ingests
all FSRS reports nightly) and writes them to the canonical output path.

Primary strategy   : USAspending /api/v2/search/spending_by_award/ (subawards=True)
Secondary strategy : Presence check — if pr_subawards_master.csv already exists
                     from download_subawards.py, derive pr_fsrs_subawards.csv from it.
Tertiary strategy  : Manual export instructions printed and exit code 1 returned.

Outputs:
  data/staging/processed/pr_fsrs_subawards.csv  — one row per PR subaward

Usage:
  python3 scripts/download_fsrs.py
  python3 scripts/download_fsrs.py --force
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT

OUT_PATH = PROCESSED_DIR / "pr_fsrs_subawards.csv"
SUBAWARD_MASTER = PROCESSED_DIR / "pr_subawards_master.csv"

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
MAX_PAGES = 50

FSRS_COLUMNS = [
    "subaward_id", "prime_award_id", "prime_award_generated_internal_id",
    "prime_recipient_name", "sub_recipient_name", "sub_recipient_uei",
    "sub_award_amount", "sub_award_date", "sub_award_type",
    "place_of_performance_state", "place_of_performance_city",
    "prime_agency_name", "cfda_number",
    "source_dataset",
]

logger = logging.getLogger(__name__)


def _paginate(session: requests.Session, payload: dict) -> list[dict]:
    rows: list[dict] = []
    page = 1
    while page <= MAX_PAGES:
        payload["page"] = page
        try:
            r = session.post(USASPENDING_URL, json=payload, timeout=60)
            r.raise_for_status()
            body = r.json()
        except Exception as exc:
            logger.warning("USAspending request failed on page %d: %s", page, exc)
            break
        for result in body.get("results", []):
            rows.append({
                "subaward_id":                      result.get("Award ID") or result.get("award_id", ""),
                "prime_award_id":                   result.get("prime_award_id", ""),
                "prime_award_generated_internal_id": result.get("prime_award_generated_internal_id", ""),
                "prime_recipient_name":             result.get("Recipient Name", ""),
                "sub_recipient_name":               result.get("recipient_name", ""),
                "sub_recipient_uei":                result.get("recipient_uei", ""),
                "sub_award_amount":                 result.get("Award Amount", 0),
                "sub_award_date":                   result.get("Start Date", ""),
                "sub_award_type":                   result.get("Award Type", ""),
                "place_of_performance_state":       result.get("Place of Performance State Code", ""),
                "place_of_performance_city":        result.get("Place of Performance City Name", ""),
                "prime_agency_name":                result.get("Awarding Agency", ""),
                "cfda_number":                      result.get("cfda_number", ""),
                "source_dataset":                   "fsrs_usaspending",
            })
        meta = body.get("page_metadata", {})
        if not meta.get("hasNext"):
            break
        page += 1
    return rows


def _fetch_via_usaspending(session: requests.Session) -> pd.DataFrame:
    payload = {
        "filters": {
            "recipient_scope": "domestic",
            "place_of_performance_locations": [{"state": "PR", "country": "USA"}],
            "award_type_codes": ["02", "03", "04", "05", "A", "B", "C", "D"],
        },
        "fields": [
            "Award ID", "Award Amount", "Award Type", "Recipient Name",
            "Start Date", "Place of Performance State Code",
            "Place of Performance City Name", "Awarding Agency",
        ],
        "subawards": True,
        "limit": 100,
        "sort": "Award Amount",
        "order": "desc",
    }
    rows = _paginate(session, payload)
    if not rows:
        return pd.DataFrame(columns=FSRS_COLUMNS)
    return pd.DataFrame(rows)[FSRS_COLUMNS]


def _derive_from_subaward_master() -> pd.DataFrame | None:
    """Derive pr_fsrs_subawards.csv from the existing usaspending subaward master."""
    if not SUBAWARD_MASTER.exists() or SUBAWARD_MASTER.stat().st_size == 0:
        return None
    try:
        df = pd.read_csv(SUBAWARD_MASTER, low_memory=False)
        if df.empty:
            return None
        out = pd.DataFrame()
        out["subaward_id"] = df.get("subaward_id", df.get("award_id", ""))
        out["prime_award_id"] = df.get("prime_award_id", "")
        out["prime_award_generated_internal_id"] = df.get("prime_award_generated_internal_id", "")
        out["prime_recipient_name"] = df.get("prime_name", df.get("recipient_name", ""))
        out["sub_recipient_name"] = df.get("sub_recipient_name", df.get("recipient_name", ""))
        out["sub_recipient_uei"] = df.get("sub_recipient_uei", "")
        out["sub_award_amount"] = df.get("sub_award_amount", df.get("obligated_amount", 0))
        out["sub_award_date"] = df.get("sub_award_date", df.get("period_of_performance_start_date", ""))
        out["sub_award_type"] = df.get("sub_award_type", df.get("award_category", "subaward"))
        out["place_of_performance_state"] = df.get("place_of_performance_state", "PR")
        out["place_of_performance_city"] = df.get("place_of_performance_city", "")
        out["prime_agency_name"] = df.get("prime_agency_name", df.get("agency_name", ""))
        out["cfda_number"] = df.get("cfda_number", "")
        out["source_dataset"] = "fsrs_derived_usaspending_master"
        return out[FSRS_COLUMNS]
    except Exception as exc:
        logger.warning("Failed to derive from subaward master: %s", exc)
        return None


def run(force: bool = False) -> dict:
    if OUT_PATH.exists() and not force:
        try:
            df = pd.read_csv(OUT_PATH)
            if not df.empty:
                logger.info("pr_fsrs_subawards.csv already present (%d rows). Use --force to refresh.", len(df))
                return {"rows": len(df), "status": "cached"}
        except Exception:
            pass

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session()

    # Strategy 1: USAspending API
    logger.info("Fetching FSRS subawards via USAspending API…")
    try:
        df = _fetch_via_usaspending(session)
        if not df.empty:
            df.to_csv(OUT_PATH, index=False)
            logger.info("USAspending strategy: %d subaward rows written.", len(df))
            return {"rows": len(df), "status": "ok_usaspending_api"}
    except Exception as exc:
        logger.warning("USAspending strategy failed: %s", exc)

    # Strategy 2: derive from existing subaward master
    logger.info("Falling back to subaward master derivation…")
    df = _derive_from_subaward_master()
    if df is not None and not df.empty:
        df.to_csv(OUT_PATH, index=False)
        logger.info("Subaward master strategy: %d rows written.", len(df))
        return {"rows": len(df), "status": "ok_derived_master"}

    # Strategy 3: write header-only and report manual needed
    logger.warning(
        "No FSRS data available. Manual export required: "
        "https://www.fsrs.gov/ → Search Subawards (PR) → Export CSV → "
        "place at data/staging/processed/pr_fsrs_subawards.csv"
    )
    pd.DataFrame(columns=FSRS_COLUMNS).to_csv(OUT_PATH, index=False)
    return {"rows": 0, "status": "manual_required"}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = run(force=args.force)
    status = result["status"]
    rows = result["rows"]
    if status.startswith("ok"):
        logger.info("✓ FSRS subawards: %d rows (%s)", rows, status)
        return 0
    elif status == "cached":
        logger.info("✓ FSRS subawards: %d rows (cached)", rows)
        return 0
    else:
        logger.warning("✗ FSRS subawards: manual export required.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
