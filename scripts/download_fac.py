"""
Download federal Single Audit results (SF-SAC) for Puerto Rico auditees from the
Federal Audit Clearinghouse (FAC) API.

Every non-federal entity that expends $750k+ in federal awards in a year files a
Single Audit; the FAC is the authoritative repository of those audits and their
findings. This captures oversight on PR subrecipients that the prime-award feeds
do not surface.

Endpoint: https://api.fac.gov/general  (PostgREST; X-Api-Key from api.data.gov)
A free key (FAC_API_KEY) is recommended: https://api.data.gov/signup/

Output:
  data/staging/processed/pr_single_audits.csv

Usage:
  python3 scripts/download_fac.py
  python3 scripts/download_fac.py --api-key YOUR_KEY
  python3 scripts/download_fac.py --force
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from moneysweep.runtime.base_downloader import (
    HttpConfig,
    PageResult,
    build_session,
    http_get_json,
    paginate,
)
from scripts.config import PROJECT_ROOT, setup_logging

_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"
FAC_URL = "https://api.fac.gov/general"
PAGE_SIZE = 500

OUTPUT_COLUMNS = [
    "report_id",
    "auditee_name",
    "auditee_ein",
    "auditee_state",
    "audit_year",
    "fy_end_date",
    "total_amount_expended",
    "number_of_findings",
    "auditor_firm_name",
]

_FIELD_MAP = {
    "report_id": "report_id",
    "auditee_name": "auditee_name",
    "auditee_ein": "auditee_ein",
    "auditee_state": "auditee_state",
    "audit_year": "audit_year",
    "fy_end_date": "fy_end_date",
    "total_amount_expended": "total_amount_expended",
    "number_of_findings": "number_of_findings",
    "auditor_firm_name": "auditor_firm_name",
}


def _fetch(session, logger) -> list[dict]:
    def _page(offset: int) -> PageResult:
        params = {
            "auditee_state": "eq.PR",
            "limit": PAGE_SIZE,
            "offset": offset,
            "order": "audit_year.desc",
        }
        config = HttpConfig(user_agent=_USER_AGENT, page_sleep=0.3)
        data: Any = http_get_json(session, FAC_URL, params, logger=logger, config=config)
        # PostgREST returns a JSON array.
        results = data if isinstance(data, list) else []
        if not results:
            return PageResult([], None)
        rows = []
        for r in results:
            row = {col: "" for col in OUTPUT_COLUMNS}
            for api_field, col in _FIELD_MAP.items():
                if api_field in r:
                    row[col] = r.get(api_field, "")
            rows.append(row)
        next_marker = offset + PAGE_SIZE if len(results) == PAGE_SIZE else None
        return PageResult(rows, next_marker)

    return list(paginate(_page, start_marker=0))


def run(root: Path | None = None, api_key: str | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_single_audits.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_fac")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    api_key = api_key or os.environ.get("FAC_API_KEY", "")
    if not api_key:
        logger.warning("  FAC_API_KEY not set — request will be limited/blocked by api.data.gov")
    session = build_session(_USER_AGENT, {"X-Api-Key": api_key} if api_key else None)

    logger.info("Fetching PR Single Audits from the Federal Audit Clearinghouse...")
    try:
        rows = _fetch(session, logger)
    finally:
        session.close()

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(df) else "NO_DATA"
    logger.info(f"  {status}: {len(df):,} single-audit records → {out_path.name}")
    return {"rows": len(df), "path": str(out_path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=None, help="FAC API key (or set FAC_API_KEY)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(api_key=args.api_key, force=args.force)
    print(f"\nSingle audits: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
