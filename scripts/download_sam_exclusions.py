"""
Download the SAM.gov exclusions (debarment) list from the SAM Entity API.

SAM exclusions are parties suspended or debarred from receiving federal awards.
This is the screening complement to ``sam_entities`` (registration/UEI
resolution) and to ``ofac_sdn`` (sanctions): any award recipient matching an
active exclusion is a compliance red flag.

Endpoint: https://api.sam.gov/entity-information/v4/exclusions  (X-Api-Key)
A SAM API key (SAM_API_KEY) is required: https://sam.gov/

Output:
  data/staging/processed/sam_exclusions.csv

Usage:
  python3 scripts/download_sam_exclusions.py
  python3 scripts/download_sam_exclusions.py --api-key YOUR_KEY
  python3 scripts/download_sam_exclusions.py --force
"""

from __future__ import annotations

import argparse
import os
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
SAM_URL = "https://api.sam.gov/entity-information/v4/exclusions"
PAGE_SIZE = 100

OUTPUT_COLUMNS = [
    "classification",
    "name",
    "exclusion_type",
    "exclusion_program",
    "excluding_agency",
    "active_date",
    "termination_date",
    "uei",
    "state",
]


def _flatten(record: dict) -> dict:
    """Best-effort flatten of a SAM exclusion record into OUTPUT_COLUMNS."""
    details = record.get("exclusionDetails", {}) or {}
    ident = record.get("exclusionIdentification", {}) or record.get(
        "samExclusionIdentification", {}
    )
    addr = record.get("exclusionActions", {}) or {}
    row = {col: "" for col in OUTPUT_COLUMNS}
    row["classification"] = ident.get("classificationType", "") or record.get("classification", "")
    row["name"] = ident.get("name", "") or ident.get("entityName", "") or record.get("name", "")
    row["exclusion_type"] = details.get("exclusionType", "") or record.get("exclusionType", "")
    row["exclusion_program"] = details.get("exclusionProgram", "") or record.get(
        "exclusionProgram", ""
    )
    row["excluding_agency"] = details.get("excludingAgencyName", "") or record.get("agency", "")
    row["active_date"] = record.get("activeDate", "") or details.get("activateDate", "")
    row["termination_date"] = record.get("terminationDate", "") or details.get(
        "terminationDate", ""
    )
    row["uei"] = ident.get("ueiSAM", "") or record.get("ueiSAM", "")
    row["state"] = (addr.get("stateProvince", "") if isinstance(addr, dict) else "") or record.get(
        "state", ""
    )
    return row


def _fetch(session, api_key: str, logger) -> list[dict]:
    def _page(page: int) -> PageResult:
        params = {
            "api_key": api_key,
            "page": page,
            "size": PAGE_SIZE,
        }
        config = HttpConfig(user_agent=_USER_AGENT, page_sleep=0.5)
        data: Any = http_get_json(session, SAM_URL, params, logger=logger, config=config)
        if not isinstance(data, dict):
            return PageResult([], None)
        results = (
            data.get("excludedEntity") or data.get("excludedEntities") or data.get("results") or []
        )
        if not results:
            return PageResult([], None)
        rows = [_flatten(r) for r in results]
        total_pages = data.get("totalPages")
        if total_pages is not None:
            next_marker = page + 1 if page + 1 < int(total_pages) else None
        else:
            next_marker = page + 1 if len(results) == PAGE_SIZE else None
        return PageResult(rows, next_marker)

    return list(paginate(_page, start_marker=0))


def run(root: Path | None = None, api_key: str | None = None, force: bool = False) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "sam_exclusions.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    logger = setup_logging("download_sam_exclusions")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    api_key = api_key or os.environ.get("SAM_API_KEY", "")
    if not api_key:
        logger.warning("  SAM_API_KEY not set — exclusions API requires a key; writing empty file")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "NO_KEY"}

    # SAM.gov exclusions v4 returns 406 when Accept: application/json is set;
    # override to wildcard so the server uses its default content negotiation.
    session = build_session(_USER_AGENT, extra_headers={"Accept": "*/*"})
    logger.info("Fetching SAM.gov exclusions (debarment list)...")
    try:
        rows = _fetch(session, api_key, logger)
    finally:
        session.close()

    df = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    df.to_csv(out_path, index=False, encoding="utf-8")
    status = "OK" if len(df) else "NO_DATA"
    logger.info(f"  {status}: {len(df):,} exclusion records → {out_path.name}")
    return {"rows": len(df), "path": str(out_path), "status": status}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", default=None, help="SAM API key (or set SAM_API_KEY)")
    parser.add_argument("--force", action="store_true", help="Re-fetch even if output exists")
    args = parser.parse_args()
    result = run(api_key=args.api_key, force=args.force)
    print(f"\nSAM exclusions: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
