"""
Download Federal Election Commission (FEC) Schedule A contributions from
Puerto Rico entities to federal candidates and committees.

Uses the FEC Open API (api.open.fec.gov). A free API key is recommended:
  https://api.data.gov/signup/
Without one, DEMO_KEY is used (30 req/hour; sufficient for small runs).

Covers election cycles 2000-2024 (13 two-year periods), contributor_state=PR.

Output:
  data/staging/raw/fec/fec_pr_contributions.csv
  data/staging/processed/pr_fec_contributions.csv

Usage:
  python3 scripts/download_fec.py
  python3 scripts/download_fec.py --api-key YOUR_KEY
  python3 scripts/download_fec.py --force
"""

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEC_BASE = "https://api.open.fec.gov/v1"
PAGE_SIZE = 100
PAGE_SLEEP_DEMO = 2.5   # stay well under 30 req/hour with DEMO_KEY
PAGE_SLEEP_KEY  = 0.2   # with a real key (1,000 req/hour)
MAX_RETRIES    = 3
RETRY_BACKOFF  = [5, 15, 30]

# Election cycles covered (FEC uses even years: the cycle ending that year)
START_CYCLE = 2000
# FEC cycles are even years; dynamically include the current cycle
def _current_fec_cycle() -> int:
    from datetime import date
    y = date.today().year
    return y if y % 2 == 0 else y + 1
END_CYCLE = _current_fec_cycle()

OUTPUT_COLUMNS = [
    "cycle",
    "contributor_name",
    "contributor_city",
    "contributor_zip_code",
    "contributor_employer",
    "contributor_occupation",
    "contribution_receipt_amount",
    "contribution_receipt_date",
    "committee_id",
    "committee_name",
    "candidate_id",
    "candidate_name",
    "report_year",
    "election_type",
    "memo_text",
    "is_individual",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _session(api_key: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR federal spending research)",
        "Accept": "application/json",
        "X-Api-Key": api_key,
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger, sleep_s: float) -> dict | None:
    """GET with retry/backoff. Returns parsed JSON or None."""
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code} — skipping: {resp.text[:200]}")
                return None
            resp.raise_for_status()
            time.sleep(sleep_s)
            return resp.json()
        except requests.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({e}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {e}")
    return None


# ---------------------------------------------------------------------------
# FEC Schedule A fetcher
# ---------------------------------------------------------------------------

def _fetch_cycle(session: requests.Session, cycle: int, sleep_s: float, logger) -> list[dict]:
    """Fetch all Schedule A contributions from PR for one election cycle."""
    url = f"{FEC_BASE}/schedules/schedule_a/"
    records = []
    page = 1

    while True:
        params = {
            "contributor_state": "PR",
            "two_year_transaction_period": cycle,
            "per_page": PAGE_SIZE,
            "page": page,
            "sort": "-contribution_receipt_date",
            "sort_hide_null": "false",
        }
        data = _get(session, url, params, logger, sleep_s)
        if data is None:
            break

        results = data.get("results", [])
        if not results:
            break

        for rec in results:
            committee = rec.get("committee") or {}
            candidate = rec.get("candidate") or {}
            records.append({
                "cycle":                       cycle,
                "contributor_name":            rec.get("contributor_name", ""),
                "contributor_city":            rec.get("contributor_city", ""),
                "contributor_zip_code":        rec.get("contributor_zip_code", ""),
                "contributor_employer":        rec.get("contributor_employer", ""),
                "contributor_occupation":      rec.get("contributor_occupation", ""),
                "contribution_receipt_amount": rec.get("contribution_receipt_amount", ""),
                "contribution_receipt_date":   rec.get("contribution_receipt_date", ""),
                "committee_id":                rec.get("committee_id", ""),
                "committee_name":              committee.get("name", rec.get("committee_name", "")),
                "candidate_id":                rec.get("candidate_id", ""),
                "candidate_name":              candidate.get("name", ""),
                "report_year":                 rec.get("report_year", ""),
                "election_type":               rec.get("election_type", ""),
                "memo_text":                   rec.get("memo_text", ""),
                "is_individual":               rec.get("entity_type", "") == "IND",
            })

        pagination = data.get("pagination", {})
        total_pages = pagination.get("pages", 1)
        count = pagination.get("count", 0)

        if page == 1 and count:
            logger.info(f"  Cycle {cycle}: {count:,} total contributions")

        if page >= total_pages:
            break
        page += 1

    return records


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run(root: Path = None, api_key: str = None, force: bool = False) -> dict:
    return _run(root=root, api_key=api_key, force=force)


def _run(root: Path = None, api_key: str = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    raw_dir     = root / "data" / "staging" / "raw" / "fec"
    raw_path    = raw_dir / "fec_pr_contributions.csv"
    master_path = root / "data" / "staging" / "processed" / "pr_fec_contributions.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_fec")

    # Resolve API key
    if not api_key:
        api_key = os.environ.get("FEC_API_KEY", "DEMO_KEY")
    is_demo = api_key == "DEMO_KEY"
    sleep_s = PAGE_SLEEP_DEMO if is_demo else PAGE_SLEEP_KEY
    if is_demo:
        logger.warning(
            "  Using DEMO_KEY (30 req/hour). Set FEC_API_KEY env var or pass --api-key "
            "for a free key from https://api.data.gov/signup/"
        )

    logger.info(f"Starting FEC Schedule A download for Puerto Rico (cycles {START_CYCLE}-{END_CYCLE})...")

    if not force and raw_path.exists():
        logger.info(f"  Raw file exists — loading for master build")
        df = pd.read_csv(raw_path, dtype=str, low_memory=False)
        all_records = df.to_dict("records")
    else:
        session   = _session(api_key)
        all_records = []
        cycles = list(range(START_CYCLE, END_CYCLE + 2, 2))  # 2000, 2002, ..., 2024

        for cycle in cycles:
            logger.info(f"  Fetching cycle {cycle}...")
            recs = _fetch_cycle(session, cycle, sleep_s, logger)
            all_records.extend(recs)
            logger.info(f"  Cycle {cycle}: {len(recs):,} records fetched")
        session.close()

        if not all_records:
            logger.warning("  No FEC records returned — writing empty master")
            pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(master_path, index=False)
            return {"rows": 0, "raw_rows": 0, "status": "EMPTY"}

        df_raw = pd.DataFrame(all_records)
        df_raw.to_csv(raw_path, index=False, encoding="utf-8")
        logger.info(f"  Raw: {len(df_raw):,} records → {raw_path.name}")

    df = pd.DataFrame(all_records) if isinstance(all_records[0], dict) else pd.read_csv(raw_path, dtype=str)

    # Ensure all output columns present
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OUTPUT_COLUMNS]

    # Deduplicate on (contributor_name, committee_id, contribution_receipt_date, amount)
    before = len(df)
    df = df.drop_duplicates(
        subset=["contributor_name", "committee_id", "contribution_receipt_date", "contribution_receipt_amount"],
        keep="first",
    )
    if len(df) < before:
        logger.info(f"  Removed {before - len(df):,} duplicate contribution records")

    df.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(df):,} rows → {master_path.name}")

    summary = {
        "rows":       len(df),
        "raw_rows":   before,
        "master_path": str(master_path),
        "status":     "OK" if len(df) > 0 else "EMPTY",
    }

    logger.info("=" * 60)
    logger.info("FEC DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Rows:   {summary['rows']:,}")
    logger.info(f"  Status: {summary['status']}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Download FEC Schedule A contributions from Puerto Rico")
    parser.add_argument("--api-key", dest="api_key", default=None,
                        help="FEC API key (default: FEC_API_KEY env var or DEMO_KEY)")
    parser.add_argument("--force", action="store_true", help="Re-download even if raw file exists")
    args = parser.parse_args()
    summary = _run(api_key=args.api_key, force=args.force)
    print(f"\nFEC download complete. {summary['rows']:,} rows.")
    return 0 if summary["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
