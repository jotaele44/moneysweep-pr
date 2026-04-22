"""
Download IRS 990 nonprofit financial data for Puerto Rico via ProPublica API.

Phase 1: List all PR-registered nonprofits (search endpoint, paginated).
Phase 2: Fetch detailed 990 filing data for organizations above a revenue
         threshold (to avoid thousands of tiny shell orgs).

Output:
  data/staging/raw/nonprofits/pr_nonprofits_raw.csv     (org list)
  data/staging/processed/pr_nonprofits.csv              (with 990 financials)

Usage:
  python3 scripts/download_nonprofits.py
  python3 scripts/download_nonprofits.py --min-revenue 100000
  python3 scripts/download_nonprofits.py --force
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

PROPUBLICA_BASE  = "https://projects.propublica.org/nonprofits/api/v2"
PAGE_SLEEP       = 0.8    # ProPublica asks for polite crawling
DETAIL_SLEEP     = 0.5
MAX_RETRIES      = 3
RETRY_BACKOFF    = [5, 15, 30]
DEFAULT_MIN_REV  = 500_000   # only fetch detail for orgs with ≥ $500K revenue

# NTEE major group labels (first letter of NTEE code)
NTEE_LABELS = {
    "A": "Arts/Culture", "B": "Education", "C": "Environment",
    "D": "Animal-Related", "E": "Health", "F": "Mental Health",
    "G": "Disease/Disorder", "H": "Medical Research", "I": "Crime/Legal",
    "J": "Employment", "K": "Food/Agriculture", "L": "Housing",
    "M": "Public Safety", "N": "Recreation/Sports", "O": "Youth Dev",
    "P": "Human Services", "Q": "International", "R": "Civil Rights",
    "S": "Community Improvement", "T": "Philanthropy/Voluntarism",
    "U": "Science/Tech", "V": "Social Science", "W": "Public/Society",
    "X": "Religion", "Y": "Mutual Benefit", "Z": "Unknown",
}

OUTPUT_COLUMNS = [
    "ein",
    "name",
    "city",
    "state",
    "ntee_code",
    "ntee_category",
    "subsection_code",
    "ruling_year",
    "latest_filing_year",
    "total_revenue",
    "total_expenses",
    "total_assets",
    "total_liabilities",
    "grants_received",
    "grants_paid",
    "officer_compensation",
    "employee_count",
    "revenue_trend",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR nonprofit research; not-for-profit)",
        "Accept":     "application/json",
    })
    return s


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=30)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if resp.status_code == 404:
                return None
            if 400 <= resp.status_code < 500:
                logger.warning(f"  HTTP {resp.status_code}: {resp.text[:120]}")
                return None
            resp.raise_for_status()
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
# Phase 1: list all PR nonprofits
# ---------------------------------------------------------------------------

def _list_orgs(session: requests.Session, logger) -> list[dict]:
    url  = f"{PROPUBLICA_BASE}/organizations/search.json"
    page = 0
    orgs = []

    while True:
        params = {"state[id]": "PR", "page": page}
        data   = _get(session, url, params, logger)
        if data is None:
            break
        batch = data.get("organizations") or []
        if not batch:
            break
        orgs.extend(batch)
        if page == 0:
            total = data.get("total_results", "?")
            logger.info(f"  ProPublica: {total} total PR nonprofits")
        time.sleep(PAGE_SLEEP)
        page += 1

    return orgs


# ---------------------------------------------------------------------------
# Phase 2: fetch detailed 990 filing for one org
# ---------------------------------------------------------------------------

def _fetch_detail(session: requests.Session, ein: str, logger) -> dict:
    url  = f"{PROPUBLICA_BASE}/organizations/{ein}.json"
    data = _get(session, url, {}, logger)
    if not data:
        return {}
    time.sleep(DETAIL_SLEEP)

    org      = data.get("organization") or {}
    filings  = data.get("filings_with_data") or []

    if not filings:
        return {}

    # Use the most recent filing with data
    latest = filings[0]

    # Revenue trend: compare latest to 3-years-prior if available
    trend = ""
    if len(filings) >= 4:
        old_rev = _num(filings[3].get("totrevenue"))
        new_rev = _num(latest.get("totrevenue"))
        if old_rev and new_rev:
            pct = (new_rev - old_rev) / abs(old_rev) * 100
            trend = f"{pct:+.0f}%"

    return {
        "latest_filing_year": latest.get("tax_prd_yr") or str(latest.get("tax_prd", ""))[:4],
        "total_revenue":      _num(latest.get("totrevenue")),
        "total_expenses":     _num(latest.get("totfuncexpns")),
        "total_assets":       _num(latest.get("totassetsend")),
        "total_liabilities":  _num(latest.get("totliabend")),
        "grants_received":    _num(latest.get("grscontrbgivingelc") or latest.get("totcntrbgfts")),
        "grants_paid":        _num(latest.get("grntspaidnfchr") or latest.get("totgrnts")),
        "officer_compensation": _num(latest.get("compnsatncurrofcr")),
        "employee_count":     latest.get("noemployees") or "",
        "revenue_trend":      trend,
    }


def _num(val) -> float | str:
    if val is None or val == "":
        return ""
    try:
        return float(val)
    except (TypeError, ValueError):
        return ""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(root: Path = None, min_revenue: float = DEFAULT_MIN_REV, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "nonprofits"
    raw_path = raw_dir / "pr_nonprofits_raw.csv"
    out_path = root / "data" / "staging" / "processed" / "pr_nonprofits.csv"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger  = setup_logging("download_nonprofits")
    session = _session()

    # ------------------------------------------------------------------
    # Phase 1: load or fetch org list
    # ------------------------------------------------------------------
    if not force and raw_path.exists():
        logger.info(f"  Org list exists — loading cached data")
        df_raw = pd.read_csv(raw_path, dtype=str, low_memory=False)
        orgs   = df_raw.to_dict("records")
    else:
        logger.info("Phase 1: Listing all PR nonprofits from ProPublica...")
        orgs = _list_orgs(session, logger)
        if not orgs:
            logger.warning("  No orgs returned — writing empty master")
            pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False)
            return {"rows": 0, "status": "EMPTY"}
        df_raw = pd.DataFrame(orgs)
        df_raw.to_csv(raw_path, index=False, encoding="utf-8")
        logger.info(f"  Phase 1 complete: {len(orgs):,} orgs → {raw_path.name}")

    # ------------------------------------------------------------------
    # Phase 2: fetch 990 detail for orgs above revenue threshold
    # ------------------------------------------------------------------
    rows = []
    for org in orgs:
        ein          = str(org.get("ein", "")).strip()
        name         = str(org.get("name", ""))
        city         = str(org.get("city", ""))
        state        = str(org.get("state", ""))
        ntee_code    = str(org.get("ntee_code", ""))
        subsection   = str(org.get("subsection_code", ""))
        ruling_year  = str(org.get("ruling_year_month", ""))[:4]
        revenue_amt  = _num(org.get("revenue_amt") or org.get("income_amt"))

        ntee_cat = NTEE_LABELS.get((ntee_code[:1] if ntee_code else ""), "Unknown")

        base = {
            "ein":             ein,
            "name":            name,
            "city":            city,
            "state":           state,
            "ntee_code":       ntee_code,
            "ntee_category":   ntee_cat,
            "subsection_code": subsection,
            "ruling_year":     ruling_year,
            "latest_filing_year": "",
            "total_revenue":   revenue_amt,
            "total_expenses":  "",
            "total_assets":    "",
            "total_liabilities": "",
            "grants_received": "",
            "grants_paid":     "",
            "officer_compensation": "",
            "employee_count":  "",
            "revenue_trend":   "",
        }

        # Fetch detail only for orgs meeting revenue threshold
        threshold = min_revenue if isinstance(revenue_amt, float) else 0
        if ein and isinstance(revenue_amt, float) and revenue_amt >= threshold:
            detail = _fetch_detail(session, ein, logger)
            base.update(detail)

        rows.append(base)

    session.close()

    df = pd.DataFrame(rows)
    for col in OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[OUTPUT_COLUMNS]
    df = df.drop_duplicates(subset=["ein"], keep="first")
    df = df.sort_values("total_revenue", ascending=False, key=lambda s: pd.to_numeric(s, errors="coerce").fillna(0))

    df.to_csv(out_path, index=False, encoding="utf-8")

    above_threshold = sum(1 for o in orgs
                         if isinstance(_num(o.get("revenue_amt") or o.get("income_amt")), float)
                         and _num(o.get("revenue_amt") or o.get("income_amt")) >= min_revenue)

    total_rev = pd.to_numeric(df["total_revenue"], errors="coerce").sum()

    logger.info("=" * 60)
    logger.info("NONPROFIT 990 DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total PR nonprofits listed:  {len(df):,}")
    logger.info(f"  Above revenue threshold:     {above_threshold:,} (≥ ${min_revenue:,.0f})")
    logger.info(f"  Combined reported revenue:   ${total_rev:,.0f}")
    logger.info(f"  Written: {out_path.name}")

    if not df.empty:
        logger.info(f"\n  Top 10 by revenue:")
        for _, row in df.head(10).iterrows():
            rev = row["total_revenue"]
            rev_str = f"${float(rev):>15,.0f}" if rev != "" else " " * 16 + "N/A"
            logger.info(f"    {str(row['name'])[:55]:<55} {rev_str}  [{row['ntee_category']}]")

    return {
        "rows":   len(df),
        "status": "OK" if len(df) > 0 else "EMPTY",
        "path":   str(out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR nonprofit 990 data via ProPublica")
    parser.add_argument("--min-revenue", type=float, default=DEFAULT_MIN_REV,
                        help=f"Minimum revenue to fetch 990 detail (default: ${DEFAULT_MIN_REV:,.0f})")
    parser.add_argument("--force", action="store_true", help="Re-fetch org list even if cached")
    args = parser.parse_args()
    result = run(min_revenue=args.min_revenue, force=args.force)
    print(f"\nNonprofit download complete. {result['rows']:,} organizations.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
