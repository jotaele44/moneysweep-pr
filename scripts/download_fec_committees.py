"""
Download FEC committee master + Schedule B (disbursements) + Schedule E
(independent expenditures) for Puerto Rico-linked political committees.

This expands FEC coverage beyond Schedule A *receipts* (already handled by
``download_fec.py``) so PACs, Super PACs, 527s, and party committees become
first-class entities in the political-finance layer rather than being embedded
only as ``committee_id`` / ``committee_name`` columns on contribution rows.

Uses the FEC Open API (api.open.fec.gov). A free API key is recommended:
  https://api.data.gov/signup/
Without one, DEMO_KEY is used (30 req/hour).

Outputs:
  data/staging/processed/pr_fec_committees.csv
  data/staging/processed/pr_fec_disbursements.csv
  data/staging/processed/pr_fec_independent_expenditures.csv

Usage:
  python3 scripts/download_fec_committees.py
  python3 scripts/download_fec_committees.py --api-key YOUR_KEY
  python3 scripts/download_fec_committees.py --force
  python3 scripts/download_fec_committees.py --skip-disbursements
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from moneysweep.runtime.base_downloader import (
    HttpConfig,
    PageResult,
    build_session,
    http_get_json,
    paginate,
)
from scripts.config import PROJECT_ROOT, setup_logging

_USER_AGENT = "ContractSweeper/1.0 (PR federal spending research)"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEC_BASE = "https://api.open.fec.gov/v1"
PAGE_SIZE = 100
PAGE_SLEEP_DEMO = 2.5
PAGE_SLEEP_KEY = 0.2
MAX_RETRIES = 3

START_CYCLE = 2000


def _current_fec_cycle() -> int:
    from datetime import date

    y = date.today().year
    return y if y % 2 == 0 else y + 1


END_CYCLE = _current_fec_cycle()

COMMITTEE_COLUMNS = [
    "committee_id",
    "name",
    "committee_type",
    "committee_type_full",
    "designation",
    "designation_full",
    "party",
    "party_full",
    "state",
    "treasurer_name",
    "first_file_date",
    "last_file_date",
    "organization_type",
]

DISBURSEMENT_COLUMNS = [
    "cycle",
    "committee_id",
    "committee_name",
    "recipient_name",
    "recipient_city",
    "recipient_state",
    "disbursement_amount",
    "disbursement_date",
    "disbursement_description",
    "disbursement_purpose_category",
    "memo_text",
]

INDEPENDENT_EXPENDITURE_COLUMNS = [
    "cycle",
    "committee_id",
    "committee_name",
    "candidate_id",
    "candidate_name",
    "support_oppose_indicator",
    "expenditure_amount",
    "expenditure_date",
    "office",
    "office_state",
    "office_district",
    "category_code_full",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------


def _session(api_key: str) -> requests.Session:
    return build_session(_USER_AGENT, {"X-Api-Key": api_key})


def _get(session: requests.Session, url: str, params: dict, logger, sleep_s: float) -> dict | None:
    config = HttpConfig(user_agent=_USER_AGENT, max_retries=MAX_RETRIES, page_sleep=sleep_s)
    return http_get_json(session, url, params, logger=logger, config=config)


# ---------------------------------------------------------------------------
# Phase 1: PR-linked committee master
# ---------------------------------------------------------------------------


def _fetch_committees(session: requests.Session, sleep_s: float, logger) -> list[dict]:
    """Fetch every FEC committee with state=PR (treasurer state or committee state)."""
    url = f"{FEC_BASE}/committees/"

    def _fetch(page: int) -> PageResult:
        params = {
            "state": "PR",
            "per_page": PAGE_SIZE,
            "page": page,
            "sort": "-last_file_date",
        }
        data = _get(session, url, params, logger, sleep_s)
        if data is None:
            return PageResult([], None)
        results = data.get("results", [])
        if not results:
            return PageResult([], None)
        rows: list[dict] = []
        for c in results:
            rows.append(
                {
                    "committee_id": c.get("committee_id", ""),
                    "name": c.get("name", ""),
                    "committee_type": c.get("committee_type", ""),
                    "committee_type_full": c.get("committee_type_full", ""),
                    "designation": c.get("designation", ""),
                    "designation_full": c.get("designation_full", ""),
                    "party": c.get("party", ""),
                    "party_full": c.get("party_full", ""),
                    "state": c.get("state", ""),
                    "treasurer_name": c.get("treasurer_name", ""),
                    "first_file_date": c.get("first_file_date", ""),
                    "last_file_date": c.get("last_file_date", ""),
                    "organization_type": c.get("organization_type", ""),
                }
            )
        pagination = data.get("pagination", {})
        total_pages = pagination.get("pages", 1)
        if page == 1:
            count = pagination.get("count", 0)
            logger.info(f"  Committees: {count:,} total PR-linked")
        next_marker = None if page >= total_pages else page + 1
        return PageResult(rows, next_marker)

    return list(paginate(_fetch, start_marker=1))


# ---------------------------------------------------------------------------
# Phase 2: disbursements (Schedule B) per committee, per cycle
# ---------------------------------------------------------------------------


def _fetch_disbursements(
    session: requests.Session,
    committee_ids: list[str],
    cycles: list[int],
    sleep_s: float,
    logger,
) -> list[dict]:
    url = f"{FEC_BASE}/schedules/schedule_b/"
    rows: list[dict] = []
    committee_lookup: dict[str, str] = {}
    for cid in committee_ids:
        for cycle in cycles:

            def _fetch(page: int, cid: str = cid, cycle: int = cycle) -> PageResult:
                params = {
                    "committee_id": cid,
                    "two_year_transaction_period": cycle,
                    "per_page": PAGE_SIZE,
                    "page": page,
                    "sort": "-disbursement_date",
                    "sort_hide_null": "false",
                }
                data = _get(session, url, params, logger, sleep_s)
                if data is None:
                    return PageResult([], None)
                results = data.get("results", [])
                if not results:
                    return PageResult([], None)
                page_rows: list[dict] = []
                for r in results:
                    cname = r.get("committee_name") or committee_lookup.get(cid, "")
                    if cname:
                        committee_lookup[cid] = cname
                    page_rows.append(
                        {
                            "cycle": cycle,
                            "committee_id": cid,
                            "committee_name": cname,
                            "recipient_name": r.get("recipient_name", ""),
                            "recipient_city": r.get("recipient_city", ""),
                            "recipient_state": r.get("recipient_state", ""),
                            "disbursement_amount": r.get("disbursement_amount", ""),
                            "disbursement_date": r.get("disbursement_date", ""),
                            "disbursement_description": r.get("disbursement_description", ""),
                            "disbursement_purpose_category": r.get(
                                "disbursement_purpose_category", ""
                            ),
                            "memo_text": r.get("memo_text", ""),
                        }
                    )
                pagination = data.get("pagination", {})
                total_pages = pagination.get("pages", 1)
                next_marker = None if page >= total_pages else page + 1
                return PageResult(page_rows, next_marker)

            rows.extend(paginate(_fetch, start_marker=1))
    return rows


# ---------------------------------------------------------------------------
# Phase 3: independent expenditures (Schedule E)
# ---------------------------------------------------------------------------


def _fetch_independent_expenditures(
    session: requests.Session,
    cycles: list[int],
    sleep_s: float,
    logger,
) -> list[dict]:
    """Independent expenditures filed by PR-linked committees."""
    url = f"{FEC_BASE}/schedules/schedule_e/"
    rows: list[dict] = []
    for cycle in cycles:

        def _fetch(page: int, cycle: int = cycle) -> PageResult:
            params = {
                "filer_state": "PR",
                "two_year_transaction_period": cycle,
                "per_page": PAGE_SIZE,
                "page": page,
                "sort": "-expenditure_date",
                "sort_hide_null": "false",
            }
            data = _get(session, url, params, logger, sleep_s)
            if data is None:
                return PageResult([], None)
            results = data.get("results", [])
            if not results:
                return PageResult([], None)
            page_rows = []
            for r in results:
                page_rows.append(
                    {
                        "cycle": cycle,
                        "committee_id": r.get("committee_id", ""),
                        "committee_name": r.get("committee_name", ""),
                        "candidate_id": r.get("candidate_id", ""),
                        "candidate_name": r.get("candidate_name", ""),
                        "support_oppose_indicator": r.get("support_oppose_indicator", ""),
                        "expenditure_amount": r.get("expenditure_amount", ""),
                        "expenditure_date": r.get("expenditure_date", ""),
                        "office": r.get("office", ""),
                        "office_state": r.get("office_state", ""),
                        "office_district": r.get("office_district", ""),
                        "category_code_full": r.get("category_code_full", ""),
                    }
                )
            pagination = data.get("pagination", {})
            total_pages = pagination.get("pages", 1)
            next_marker = None if page >= total_pages else page + 1
            return PageResult(page_rows, next_marker)

        rows.extend(paginate(_fetch, start_marker=1))
    return rows


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run(
    root: Path | None = None,
    api_key: str | None = None,
    force: bool = False,
    skip_disbursements: bool = False,
    skip_expenditures: bool = False,
) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)

    processed_dir = root / "data" / "staging" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)
    committees_path = processed_dir / "pr_fec_committees.csv"
    disbursements_path = processed_dir / "pr_fec_disbursements.csv"
    expenditures_path = processed_dir / "pr_fec_independent_expenditures.csv"

    logger = setup_logging("download_fec_committees")

    if not api_key:
        api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    is_demo = api_key == "DEMO_KEY"
    sleep_s = PAGE_SLEEP_DEMO if is_demo else PAGE_SLEEP_KEY
    if is_demo:
        logger.warning(
            "  Using DEMO_KEY (30 req/hour). Set FEC_API_KEY env var or pass --api-key "
            "for a free key from https://api.data.gov/signup/"
        )

    if not force and committees_path.exists():
        df = pd.read_csv(committees_path, dtype=str, low_memory=False)
        if len(df) > 0:
            logger.info(f"  Cached — {len(df):,} committees in {committees_path.name}")
            committees = df.to_dict("records")
            committee_ids = df["committee_id"].dropna().astype(str).tolist()
        else:
            committees, committee_ids = [], []
    else:
        logger.info("Phase 1: Fetching PR-linked FEC committees...")
        session_obj = _session(api_key)
        try:
            committees = _fetch_committees(session_obj, sleep_s, logger)
        finally:
            session_obj.close()
        df = pd.DataFrame(committees, columns=COMMITTEE_COLUMNS)
        df.to_csv(committees_path, index=False, encoding="utf-8")
        committee_ids = df["committee_id"].dropna().astype(str).tolist()
        logger.info(f"  Phase 1 complete: {len(df):,} committees → {committees_path.name}")

    cycles = list(range(START_CYCLE, END_CYCLE + 1, 2))

    # Phase 2: disbursements
    if skip_disbursements:
        logger.info("  Phase 2 SKIPPED (--skip-disbursements)")
        if not disbursements_path.exists():
            pd.DataFrame(columns=DISBURSEMENT_COLUMNS).to_csv(
                disbursements_path, index=False, encoding="utf-8"
            )
        disb_rows = 0
    elif not committee_ids:
        logger.info("  Phase 2: no committee_ids — writing empty disbursements file")
        pd.DataFrame(columns=DISBURSEMENT_COLUMNS).to_csv(
            disbursements_path, index=False, encoding="utf-8"
        )
        disb_rows = 0
    else:
        logger.info(
            f"Phase 2: Fetching Schedule B disbursements for "
            f"{len(committee_ids):,} committees × {len(cycles)} cycles..."
        )
        session_obj = _session(api_key)
        try:
            disbursements = _fetch_disbursements(
                session_obj, committee_ids, cycles, sleep_s, logger
            )
        finally:
            session_obj.close()
        ddf = pd.DataFrame(disbursements, columns=DISBURSEMENT_COLUMNS)
        ddf.to_csv(disbursements_path, index=False, encoding="utf-8")
        disb_rows = len(ddf)
        logger.info(f"  Phase 2 complete: {disb_rows:,} disbursements → {disbursements_path.name}")

    # Phase 3: independent expenditures
    if skip_expenditures:
        logger.info("  Phase 3 SKIPPED (--skip-expenditures)")
        if not expenditures_path.exists():
            pd.DataFrame(columns=INDEPENDENT_EXPENDITURE_COLUMNS).to_csv(
                expenditures_path, index=False, encoding="utf-8"
            )
        exp_rows = 0
    else:
        logger.info(
            f"Phase 3: Fetching Schedule E independent expenditures × {len(cycles)} cycles..."
        )
        session_obj = _session(api_key)
        try:
            expenditures = _fetch_independent_expenditures(session_obj, cycles, sleep_s, logger)
        finally:
            session_obj.close()
        edf = pd.DataFrame(expenditures, columns=INDEPENDENT_EXPENDITURE_COLUMNS)
        edf.to_csv(expenditures_path, index=False, encoding="utf-8")
        exp_rows = len(edf)
        logger.info(f"  Phase 3 complete: {exp_rows:,} expenditures → {expenditures_path.name}")

    return {
        "rows": len(committees) if committees else len(df),
        "committees": len(committees) if committees else len(df),
        "disbursements": disb_rows,
        "independent_expenditures": exp_rows,
        "status": "OK",
        "paths": {
            "committees": str(committees_path),
            "disbursements": str(disbursements_path),
            "independent_expenditures": str(expenditures_path),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download FEC committees + Schedule B/E for PR-linked committees."
    )
    parser.add_argument("--api-key", default=None, help="FEC API key (or set FEC_API_KEY)")
    parser.add_argument("--force", action="store_true", help="Re-fetch committee master")
    parser.add_argument(
        "--skip-disbursements", action="store_true", help="Skip Phase 2 (Schedule B)"
    )
    parser.add_argument(
        "--skip-expenditures", action="store_true", help="Skip Phase 3 (Schedule E)"
    )
    args = parser.parse_args()
    result = run(
        api_key=args.api_key,
        force=args.force,
        skip_disbursements=args.skip_disbursements,
        skip_expenditures=args.skip_expenditures,
    )
    print(
        f"\nFEC committees: {result['committees']:,} | "
        f"disbursements: {result['disbursements']:,} | "
        f"independent expenditures: {result['independent_expenditures']:,}"
    )
    return 0 if result["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
