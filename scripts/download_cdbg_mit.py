"""
Download HUD CDBG-Mitigation (CDBG-MIT) financial assistance to Puerto Rico from
the USASpending API.

CDBG-MIT is the long-term *mitigation* allocation HUD made after the 2017
disasters — distinct from CDBG-Disaster Recovery (``hud_cdbg_dr_public``) and
CDBG-DR grant reporting (``hud_drgr_authorized``). It is identified by CFDA/
Assistance Listing 14.272.

Endpoint: https://api.usaspending.gov/api/v2/search/spending_by_award/  (no key)

Output:
  data/staging/processed/pr_cdbg_mit.csv

Usage:
  python3 scripts/download_cdbg_mit.py
  python3 scripts/download_cdbg_mit.py --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from moneysweep.runtime.base_downloader import (
    HttpConfig,
    PageResult,
    build_session,
    http_post_json,
    paginate,
)
from scripts.config import PROJECT_ROOT, setup_logging

_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"
SEARCH_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"
PAGE_SIZE = 100
CDBG_MIT_CFDA = "14.272"

OUTPUT_COLUMNS = [
    "award_id",
    "grantee_name",
    "awarding_sub_agency",
    "award_amount",
    "action_date",
    "cfda_number",
    "cfda_title",
    "place_of_performance",
]

_REQUEST_FIELDS = [
    "Award ID",
    "Recipient Name",
    "Awarding Sub Agency",
    "Award Amount",
    "Start Date",
    "CFDA Number",
]
_FIELD_MAP = {
    "Award ID": "award_id",
    "Recipient Name": "grantee_name",
    "Awarding Sub Agency": "awarding_sub_agency",
    "Award Amount": "award_amount",
    "Start Date": "action_date",
    "CFDA Number": "cfda_number",
}


def _fetch(session, logger) -> list[dict]:
    def _page(page: int) -> PageResult:
        payload = {
            "filters": {
                "award_type_codes": ["02", "03", "04", "05"],  # grant instruments
                "program_numbers": [CDBG_MIT_CFDA],
                "recipient_locations": [{"country": "USA", "state": "PR"}],
            },
            "fields": _REQUEST_FIELDS,
            "page": page,
            "limit": PAGE_SIZE,
            "sort": "Award Amount",
            "order": "desc",
            "subawards": False,
        }
        config = HttpConfig(user_agent=_USER_AGENT, page_sleep=0.3)
        data = http_post_json(session, SEARCH_URL, payload, logger=logger, config=config)
        if not data:
            return PageResult([], None)
        results = data.get("results", []) or []
        rows = []
        for r in results:
            row = {col: "" for col in OUTPUT_COLUMNS}
            for api_field, col in _FIELD_MAP.items():
                if api_field in r:
                    row[col] = r.get(api_field, "")
            rows.append(row)
        has_next = data.get("page_metadata", {}).get("hasNext", False)
        return PageResult(rows, page + 1 if has_next else None)

    return list(paginate(_page, start_marker=1))


def run(root: Path | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_cdbg_mit.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_cdbg_mit")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    logger.info("Fetching PR HUD CDBG-MIT (CFDA 14.272) from USASpending...")
    session = build_session(_USER_AGENT)
    try:
        rows = _fetch(session, logger)
    finally:
        session.close()

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(df) else "NO_DATA"
    logger.info(f"  {status}: {len(df):,} CDBG-MIT records → {out_path.name}")
    return {"rows": len(df), "path": str(out_path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nCDBG-MIT: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
