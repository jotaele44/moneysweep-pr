"""
Download PR *municipal* Single Audit (SF-SAC) results from the Federal Audit
Clearinghouse (FAC) API.

Puerto Rico's 78 municipios are non-federal entities that expend federal awards
and therefore file Single Audits with the FAC. This narrows the FAC `general`
feed to municipal auditees, giving a machine-readable view of municipal audited
financials (total federal awards expended + finding counts) — the API-switch for
the previously scraper-bound `municipal_finance` source (issues #277 / #302).

It reuses the same FAC PostgREST endpoint and field map as `download_fac.py`
(`federal_audit_clearinghouse`); the only difference is a municipal name filter.

Endpoint: https://api.fac.gov/general  (PostgREST; X-Api-Key from api.data.gov)
A free key (FAC_API_KEY) is recommended: https://api.data.gov/signup/

Output:
  data/staging/processed/pr_municipal_finance.csv

Usage:
  python3 scripts/download_fac_municipal.py
  python3 scripts/download_fac_municipal.py --api-key YOUR_KEY
  python3 scripts/download_fac_municipal.py --force
"""

from __future__ import annotations

import argparse
import os
import re
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

_USER_AGENT = "ContractSweeper/1.0 (PR municipal finance research)"
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

_FIELD_MAP = {col: col for col in OUTPUT_COLUMNS}

# A PR municipal auditee is named either "MUNICIPIO DE <X>" (Spanish, the common
# FAC form) or "MUNICIPALITY OF <X>" (English). Matched case-insensitively.
_MUNICIPAL_RE = re.compile(r"\bMUNICIPIO\b|\bMUNICIPALITY OF\b", re.IGNORECASE)


def is_municipal(auditee_name: str) -> bool:
    """True if the auditee name looks like a PR municipality."""
    return bool(_MUNICIPAL_RE.search(auditee_name or ""))


def parse_records(records: list[dict], *, municipal_only: bool = True) -> pd.DataFrame:
    """Map raw FAC `general` records onto OUTPUT_COLUMNS, optionally keeping only
    municipal auditees, and return a deterministically sorted DataFrame."""
    rows: list[dict] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        row = {col: "" for col in OUTPUT_COLUMNS}
        for api_field, col in _FIELD_MAP.items():
            if api_field in r and r.get(api_field) is not None:
                row[col] = str(r.get(api_field, "")).strip()
        if municipal_only and not is_municipal(row["auditee_name"]):
            continue
        rows.append(row)
    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    if not df.empty:
        df = df.sort_values(
            ["audit_year", "auditee_name", "report_id"], ascending=[False, True, True]
        ).reset_index(drop=True)
    return df


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
        # PostgREST returns a JSON array; transport failure -> None -> stop.
        results = data if isinstance(data, list) else []
        if not results:
            return PageResult([], None)
        next_marker = offset + PAGE_SIZE if len(results) == PAGE_SIZE else None
        return PageResult(results, next_marker)

    return list(paginate(_page, start_marker=0))


def run(root: Path | None = None, api_key: str | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_municipal_finance.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_fac_municipal")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    api_key = api_key or os.environ.get("FAC_API_KEY", "")
    if not api_key:
        logger.warning("  FAC_API_KEY not set — request will be limited/blocked by api.data.gov")
    session = build_session(_USER_AGENT, {"X-Api-Key": api_key} if api_key else None)

    logger.info("Fetching PR municipal Single Audits from the Federal Audit Clearinghouse...")
    try:
        records = _fetch(session, logger)
    finally:
        session.close()

    df = parse_records(records, municipal_only=True)
    df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(df) else "NO_DATA"
    logger.info(f"  {status}: {len(df):,} municipal single-audit records → {out_path.name}")
    return {"rows": len(df), "path": str(out_path), "status": status}


# Entrypoint aliases for the automatable-source runner (it probes run/main/fetch/download).
download = run
fetch = run


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=None, help="FAC API key (or set FAC_API_KEY)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(api_key=args.api_key, force=args.force)
    print(f"\nMunicipal single audits: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
