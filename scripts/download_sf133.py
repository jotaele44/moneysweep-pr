"""
Download SF-133 budget execution data for PR-relevant federal programs via USASpending
federal accounts API. Tracks appropriation → obligation → outlay flow.

A low obligation_rate means federal money is sitting unspent.

Outputs:
  data/staging/processed/pr_sf133_budget_execution.csv

Usage:
  python3 scripts/download_sf133.py
  python3 scripts/download_sf133.py --force
  python3 scripts/download_sf133.py --fy-start 2017
"""

import argparse
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

FEDERAL_ACCOUNTS_URL = "https://api.usaspending.gov/api/v2/federal_accounts/"
ACCOUNT_DETAIL_URL   = "https://api.usaspending.gov/api/v2/federal_accounts/{}/available_object_classes/"

PAGE_SIZE    = 100
PAGE_SLEEP   = 0.3
MAX_RETRIES  = 3
RETRY_BACKOFF = [5, 15, 30]

# PR-relevant agencies: FEMA=58, HUD=86, DOT=69, DOE=89, USDA=12, Army=21, SBA=73, HHS=75
PR_AGENCIES = {
    "058": "FEMA",
    "086": "HUD",
    "069": "DOT",
    "089": "DOE",
    "012": "USDA",
    "021": "Army",
    "073": "SBA",
    "075": "HHS",
    "097": "DOD",
}

# PR-relevant keyword filters for account titles
PR_KEYWORDS = [
    "puerto rico", "disaster", "recovery", "reconstruction",
    "community development", "housing", "infrastructure",
    "highway", "energy", "agriculture", "small business",
]

OUTPUT_COLUMNS = [
    "fiscal_year", "agency_code", "agency_name", "account_number",
    "account_title", "budget_authority", "obligations",
    "outlays", "unobligated_balance", "obligation_rate",
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 30s")
                time.sleep(30)
                continue
            if 400 <= resp.status_code < 500:
                logger.debug(f"  HTTP {resp.status_code}: {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  All retries failed: {exc}")
    return None


def _post(session: requests.Session, url: str, payload: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, json=payload, timeout=30)
            if resp.status_code == 429:
                time.sleep(30)
                continue
            if 400 <= resp.status_code < 500:
                logger.debug(f"  HTTP {resp.status_code}: {url} — {resp.text[:200]}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.error(f"  All retries failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def _fetch_accounts(session: requests.Session, agency_code: str,
                    fy_start: int, fy_end: int, logger) -> list[dict]:
    """Fetch all federal accounts for an agency across fiscal years."""
    accounts = []
    for fy in range(fy_start, fy_end + 1):
        page = 1
        while True:
            payload = {
                "filters": {"agency_identifier": agency_code},
                "page": page,
                "limit": PAGE_SIZE,
                "sort": "budgetary_resources",
                "order": "desc",
                "fy": str(fy),
            }
            data = _post(session, FEDERAL_ACCOUNTS_URL, payload, logger)
            if not data:
                break
            results = data.get("results", [])
            if not results:
                break
            for acct in results:
                title = (acct.get("account_title") or "").lower()
                # Keep accounts that mention PR-relevant topics or have large balances
                budget = float(acct.get("budgetary_resources") or 0)
                is_relevant = (
                    any(kw in title for kw in PR_KEYWORDS)
                    or budget > 1_000_000_000  # >$1B accounts are always tracked
                )
                if is_relevant:
                    accounts.append({
                        "fiscal_year": fy,
                        "agency_code": agency_code,
                        "agency_name": PR_AGENCIES.get(agency_code, agency_code),
                        "account_number": acct.get("account_number", ""),
                        "account_title": acct.get("account_title", ""),
                        "budget_authority": budget,
                        "obligations": float(acct.get("obligations") or 0),
                        "outlays": float(acct.get("outlays") or 0),
                        "unobligated_balance": float(acct.get("unobligated_balance") or 0),
                    })
            page += 1
            if not data.get("hasNext", False) and page > data.get("page_metadata", {}).get("total", 1):
                break
            # Also break if we got fewer than a full page
            if len(results) < PAGE_SIZE:
                break
    return accounts


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False,
        fy_start: int = 2017, fy_end: int = 2026) -> dict:
    root = Path(root or PROJECT_ROOT)
    out_path = root / "data" / "staging" / "processed" / "pr_sf133_budget_execution.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_sf133", log_dir=root / "data" / "logs")

    if out_path.exists() and not force:
        rows = sum(1 for _ in open(out_path)) - 1
        logger.info(f"  SF-133: {out_path.name} exists ({rows:,} rows) — skipping. Use --force to re-download.")
        return {"status": "CACHED", "rows": rows}

    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "ContractSweeper/1.0 (PR federal spending research)",
    })

    all_accounts = []
    for code, name in PR_AGENCIES.items():
        logger.info(f"  Fetching {name} (agency {code}) FY{fy_start}–{fy_end}...")
        accounts = _fetch_accounts(session, code, fy_start, fy_end, logger)
        logger.info(f"    → {len(accounts):,} relevant accounts")
        all_accounts.extend(accounts)

    if not all_accounts:
        logger.warning("  No SF-133 data retrieved — writing empty output")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
        return {"status": "EMPTY", "rows": 0}

    df = pd.DataFrame(all_accounts)

    # Compute obligation rate (avoid div/0)
    df["obligation_rate"] = df.apply(
        lambda r: round(r["obligations"] / r["budget_authority"], 4)
        if r["budget_authority"] > 0 else 0.0,
        axis=1,
    )

    df = df[OUTPUT_COLUMNS].drop_duplicates(
        subset=["fiscal_year", "agency_code", "account_number"]
    ).sort_values(["fiscal_year", "agency_code", "budget_authority"], ascending=[False, True, False])

    df.to_csv(out_path, index=False)
    rows = len(df)
    logger.info(f"  SF-133: {rows:,} account-year rows → {out_path.name}")

    total_budget = df["budget_authority"].sum()
    total_obligated = df["obligations"].sum()
    avg_rate = round(total_obligated / total_budget, 3) if total_budget > 0 else 0
    logger.info(f"  Total budget authority: ${total_budget:,.0f}")
    logger.info(f"  Total obligated:        ${total_obligated:,.0f} ({avg_rate:.1%})")

    return {"status": "OK", "rows": rows, "total_budget": total_budget,
            "total_obligated": total_obligated, "avg_obligation_rate": avg_rate}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download SF-133 budget execution data")
    parser.add_argument("--force", action="store_true", help="Re-download even if output exists")
    parser.add_argument("--fy-start", type=int, default=2017, help="First fiscal year (default: 2017)")
    parser.add_argument("--fy-end", type=int, default=2026, help="Last fiscal year (default: 2026)")
    args = parser.parse_args()
    result = run(force=args.force, fy_start=args.fy_start, fy_end=args.fy_end)
    return 0 if result.get("status") in ("OK", "CACHED") else 1


if __name__ == "__main__":
    sys.exit(main())
