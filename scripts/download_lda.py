"""
Download Senate Lobbying Disclosure Act (LDA) filings involving Puerto Rico.

Captures two groups:
  1. PR-based clients that hired federal lobbyists   (client_state=PR)
  2. PR-based lobbying registrant firms              (registrant_state=PR)

Uses the Senate LDA Open Data API (lda.senate.gov/api/v1/).
Read access works unauthenticated; register for a token to raise rate limits:
  https://lda.senate.gov/api/auth/register/

Output:
  data/staging/raw/lda/lda_pr_filings.csv
  data/staging/processed/pr_lda_filings.csv

Usage:
  python3 scripts/download_lda.py
  python3 scripts/download_lda.py --api-key YOUR_TOKEN
  python3 scripts/download_lda.py --force
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

LDA_BASE      = "https://lda.senate.gov/api/v1"
PAGE_SIZE     = 25        # LDA API max
PAGE_SLEEP    = 0.5       # seconds between pages
MAX_RETRIES   = 3
RETRY_BACKOFF = [10, 30, 60]

OUTPUT_COLUMNS = [
    "filing_uuid",
    "filing_year",
    "filing_type",
    "period_of_report",
    "registrant_id",
    "registrant_name",
    "registrant_state",
    "client_id",
    "client_name",
    "client_state",
    "client_description",
    "income",
    "expenses",
    "general_issue_codes",
    "issue_descriptions",
    "lobbyist_names",
    "dt_posted",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _session(api_key: str | None) -> requests.Session:
    s = requests.Session()
    headers = {
        "User-Agent": "ContractSweeper/1.0 (PR federal spending research)",
        "Accept":     "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Token {api_key}"
    s.headers.update(headers)
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
                logger.error(f"  HTTP {resp.status_code}: {resp.text[:200]}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt + 1} failed ({exc}) — retry in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Record flattening
# ---------------------------------------------------------------------------

def _flatten(rec: dict) -> dict:
    registrant = rec.get("registrant") or {}
    client     = rec.get("client") or {}

    activities = rec.get("lobbying_activities") or []
    issue_codes = []
    issue_descs = []
    lobbyist_names = []
    for act in activities:
        code = act.get("general_issue_code_display") or act.get("general_issue_code") or ""
        if code and code not in issue_codes:
            issue_codes.append(code)
        desc = (act.get("description") or "").strip()
        if desc:
            issue_descs.append(desc[:120])
        for lob in act.get("lobbyists") or []:
            name = (lob.get("lobbyist", {}) or {}).get("name") or lob.get("name") or ""
            if name and name not in lobbyist_names:
                lobbyist_names.append(name)

    reg_address = registrant.get("address") or {}
    cli_address = client.get("address") or {}

    reg_state = (
        registrant.get("state")
        or reg_address.get("state")
        or ""
    )
    cli_state = (
        client.get("state")
        or cli_address.get("state")
        or ""
    )

    return {
        "filing_uuid":       rec.get("filing_uuid", ""),
        "filing_year":       rec.get("filing_year", ""),
        "filing_type":       rec.get("filing_type", ""),
        "period_of_report":  rec.get("period_of_report", ""),
        "registrant_id":     registrant.get("id", ""),
        "registrant_name":   registrant.get("name", ""),
        "registrant_state":  reg_state,
        "client_id":         client.get("id", ""),
        "client_name":       client.get("name", ""),
        "client_state":      cli_state,
        "client_description": (client.get("general_description") or "")[:200],
        "income":            rec.get("income", ""),
        "expenses":          rec.get("expenses", ""),
        "general_issue_codes": "|".join(issue_codes[:10]),
        "issue_descriptions":  "|".join(issue_descs[:5]),
        "lobbyist_names":      "|".join(lobbyist_names[:15]),
        "dt_posted":          rec.get("dt_posted", ""),
    }


# ---------------------------------------------------------------------------
# Fetch one pass (one state filter)
# ---------------------------------------------------------------------------

def _fetch_pass(session: requests.Session, state_param: str, logger) -> list[dict]:
    """Fetch all filings for one state filter (client_state or registrant_state)."""
    url  = f"{LDA_BASE}/filings/"
    page = 1
    records = []

    while True:
        params = {
            state_param: "PR",
            "page_size":  PAGE_SIZE,
            "page":       page,
        }
        data = _get(session, url, params, logger)
        if data is None:
            logger.warning(f"  [{state_param}=PR] Page {page} failed — stopping pass")
            break

        results = data.get("results") or []
        if not results:
            break

        for rec in results:
            records.append(_flatten(rec))

        count = data.get("count", 0)
        if page == 1:
            total_pages = -(-count // PAGE_SIZE)  # ceiling division
            logger.info(f"  [{state_param}=PR] {count:,} total filings (~{total_pages} pages)")

        if not data.get("next"):
            break
        page += 1

    return records


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(root: Path = None, api_key: str = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root        = Path(root)
    raw_dir     = root / "data" / "staging" / "raw" / "lda"
    raw_path    = raw_dir / "lda_pr_filings.csv"
    out_path    = root / "data" / "staging" / "processed" / "pr_lda_filings.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_lda")

    if not api_key:
        api_key = os.environ.get("LDA_API_KEY", "").strip() or None

    if not api_key:
        logger.warning(
            "  No LDA_API_KEY set — using unauthenticated access (lower rate limits).\n"
            "  Register for a free token: https://lda.senate.gov/api/auth/register/"
        )

    if not force and raw_path.exists():
        logger.info(f"  Raw file exists — loading cached data")
        df_raw = pd.read_csv(raw_path, dtype=str, low_memory=False)
        all_records = df_raw.to_dict("records")
    else:
        logger.info("Starting LDA lobbying disclosure download for Puerto Rico...")
        session = _session(api_key)

        logger.info("  Pass 1: PR-based lobbying clients (client_state=PR)...")
        client_recs = _fetch_pass(session, "client_state", logger)
        logger.info(f"  Pass 1 complete: {len(client_recs):,} filings")

        logger.info("  Pass 2: PR-based registrant firms (registrant_state=PR)...")
        registrant_recs = _fetch_pass(session, "registrant_state", logger)
        logger.info(f"  Pass 2 complete: {len(registrant_recs):,} filings")

        session.close()

        all_records = client_recs + registrant_recs
        if not all_records:
            logger.warning("  No LDA records returned — writing empty master")
            pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
            return {"rows": 0, "status": "EMPTY"}

        df_raw = pd.DataFrame(all_records)
        df_raw.to_csv(raw_path, index=False, encoding="utf-8")
        logger.info(f"  Raw: {len(df_raw):,} records → {raw_path.name}")

    df = pd.DataFrame(all_records)

    # Ensure all output columns
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OUTPUT_COLUMNS]

    # Deduplicate by filing_uuid
    before = len(df)
    df = df.drop_duplicates(subset=["filing_uuid"], keep="first")
    if len(df) < before:
        logger.info(f"  Removed {before - len(df):,} duplicate filings (same UUID from both passes)")

    # Numeric income/expenses for summary
    df["_income_num"]   = pd.to_numeric(df["income"],   errors="coerce").fillna(0)
    df["_expenses_num"] = pd.to_numeric(df["expenses"], errors="coerce").fillna(0)

    df.to_csv(out_path, index=False, encoding="utf-8")

    total_income   = df["_income_num"].sum()
    total_expenses = df["_expenses_num"].sum()
    client_pr  = (df["client_state"] == "PR").sum()
    registrant_pr = (df["registrant_state"] == "PR").sum()

    df.drop(columns=["_income_num", "_expenses_num"], inplace=True, errors="ignore")

    logger.info("=" * 60)
    logger.info("LDA LOBBYING DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total filings (deduped): {len(df):,}")
    logger.info(f"  PR-client filings:       {client_pr:,}")
    logger.info(f"  PR-registrant filings:   {registrant_pr:,}")
    logger.info(f"  Total registrant income: ${total_income:,.0f}")
    logger.info(f"  Total client expenses:   ${total_expenses:,.0f}")
    logger.info(f"  Written: {out_path.name}")

    return {
        "rows":   len(df),
        "status": "OK" if len(df) > 0 else "EMPTY",
        "path":   str(out_path),
        "client_pr_filings":     int(client_pr),
        "registrant_pr_filings": int(registrant_pr),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download LDA lobbying filings for Puerto Rico")
    parser.add_argument("--api-key", dest="api_key", default=None,
                        help="LDA API token (default: LDA_API_KEY env var)")
    parser.add_argument("--force", action="store_true", help="Re-download even if raw file exists")
    args = parser.parse_args()
    result = run(api_key=args.api_key, force=args.force)
    print(f"\nLDA download complete. {result['rows']:,} filings.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
