"""
Download FEMA Individual Assistance (Individuals & Households Program) housing
aid to Puerto Rico from the OpenFEMA API.

This is the direct-to-household disaster flow — distinct from FEMA Public
Assistance (``fema_pa_openfema_v2``, money to government/nonprofit applicants)
and HMGP mitigation grants (``fema_hmgp``). Uses the county-aggregated
``HousingAssistanceOwners`` dataset.

Endpoint: https://www.fema.gov/api/open/v2/HousingAssistanceOwners  (no key)

Output:
  data/staging/processed/pr_fema_ia.csv

Usage:
  python3 scripts/download_fema_ia.py
  python3 scripts/download_fema_ia.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from contract_sweeper.runtime.base_downloader import (
    HttpConfig,
    PageResult,
    build_session,
    http_get_json,
    paginate,
)
from scripts.config import PROJECT_ROOT, setup_logging

_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"
FEMA_URL = "https://www.fema.gov/api/open/v2/HousingAssistanceOwners"
PAGE_SIZE = 1000
DATASET_KEY = "HousingAssistanceOwners"

OUTPUT_COLUMNS = [
    "disaster_number",
    "state",
    "county",
    "city",
    "zip_code",
    "valid_registrations",
    "total_approved_ihp_amount",
    "total_housing_amount",
    "total_other_amount",
]

_FIELD_MAP = {
    "disasterNumber": "disaster_number",
    "state": "state",
    "county": "county",
    "city": "city",
    "zipCode": "zip_code",
    "validRegistrations": "valid_registrations",
    "totalApprovedIhpAmount": "total_approved_ihp_amount",
    "totalHousingAmount": "total_housing_amount",
    "totalOtherNeedsAmount": "total_other_amount",
}


def _fetch(session, logger) -> list[dict]:
    def _page(skip: int) -> PageResult:
        params = {
            "$filter": "state eq 'PR'",
            "$top": PAGE_SIZE,
            "$skip": skip,
        }
        config = HttpConfig(user_agent=_USER_AGENT, page_sleep=0.3)
        data: Any = http_get_json(session, FEMA_URL, params, logger=logger, config=config)
        if not isinstance(data, dict):
            return PageResult([], None)
        results = data.get(DATASET_KEY, []) or []
        if not results:
            return PageResult([], None)
        rows = []
        for r in results:
            row = {col: "" for col in OUTPUT_COLUMNS}
            for api_field, col in _FIELD_MAP.items():
                if api_field in r:
                    row[col] = r.get(api_field, "")
            rows.append(row)
        next_marker = skip + PAGE_SIZE if len(results) == PAGE_SIZE else None
        return PageResult(rows, next_marker)

    return list(paginate(_page, start_marker=0))


def run(root: Path | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_fema_ia.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_fema_ia")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    logger.info("Fetching PR FEMA Individual Assistance (IHP) from OpenFEMA...")
    session = build_session(_USER_AGENT)
    try:
        rows = _fetch(session, logger)
    finally:
        session.close()

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(df) else "NO_DATA"
    logger.info(f"  {status}: {len(df):,} IHP records → {out_path.name}")
    return {"rows": len(df), "path": str(out_path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFEMA Individual Assistance: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
