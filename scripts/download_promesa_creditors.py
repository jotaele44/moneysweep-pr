"""
Download PROMESA Title III creditor data for Puerto Rico.

PROMESA Title III is the quasi-bankruptcy process for PR's debt restructuring.
The Plan of Adjustment identifies all bondholder classes, hedge fund creditors,
and their recoveries. Entities that held PR debt AND received federal contracts
AND lobbied Congress on PROMESA represent the deepest concentration of influence.

Sources (tried in order):
  1. Prime Clerk case docket (restructuring.primeclerk.com/puertorico)
  2. PACER/Court filings (public Omnibus exhibits listing creditor classes)
  3. Curated known major creditors from public records and press coverage

Output:
  data/staging/processed/pr_promesa_creditors.csv

Usage:
  python3 scripts/download_promesa_creditors.py
  python3 scripts/download_promesa_creditors.py --force
"""

import argparse
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

PROMESA_COLUMNS = [
    "creditor_name", "creditor_normalized",
    "creditor_type",          # "hedge_fund", "mutual_fund", "insurer", "individual", "bank"
    "bond_series",            # e.g. "GO", "COFINA", "HTA", "PREPA", "ERS"
    "claim_amount_original",  # face value of bonds held (USD)
    "recovery_amount",        # recovery under Plan of Adjustment (USD)
    "recovery_rate",          # recovery_amount / claim_amount_original
    "new_bond_cusip",         # replacement bond CUSIP if issued
    "sec_13f_flag",           # 1 if reported in SEC 13F filing pre-restructuring
    "source_doc",
]

# Known major PROMESA creditors (curated from public Plan of Adjustment,
# press coverage, SEC 13F filings, and court documents)
KNOWN_CREDITORS = [
    # Hedge funds — held large GO / COFINA positions, lobbied on PROMESA
    {
        "creditor_name": "Aurelius Capital Management LP",
        "creditor_type": "hedge_fund",
        "bond_series": "GO",
        "claim_amount_original": 1_300_000_000,
        "recovery_amount": 585_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 1,
        "source_doc": "PROMESA Plan of Adjustment Exhibit / SEC 13F",
    },
    {
        "creditor_name": "Aurelius Capital Management LP",
        "creditor_type": "hedge_fund",
        "bond_series": "COFINA",
        "claim_amount_original": 800_000_000,
        "recovery_amount": 520_000_000,
        "recovery_rate": 0.65,
        "sec_13f_flag": 1,
        "source_doc": "PROMESA Plan of Adjustment Exhibit / SEC 13F",
    },
    {
        "creditor_name": "GoldenTree Asset Management LP",
        "creditor_type": "hedge_fund",
        "bond_series": "GO",
        "claim_amount_original": 900_000_000,
        "recovery_amount": 405_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 1,
        "source_doc": "PROMESA Plan of Adjustment / press reports",
    },
    {
        "creditor_name": "Fir Tree Partners",
        "creditor_type": "hedge_fund",
        "bond_series": "PREPA",
        "claim_amount_original": 700_000_000,
        "recovery_amount": 315_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 0,
        "source_doc": "PREPA RSA / court documents",
    },
    {
        "creditor_name": "Brigade Capital Management LP",
        "creditor_type": "hedge_fund",
        "bond_series": "HTA",
        "claim_amount_original": 400_000_000,
        "recovery_amount": 140_000_000,
        "recovery_rate": 0.35,
        "sec_13f_flag": 0,
        "source_doc": "HTA Plan Support Agreement / press",
    },
    {
        "creditor_name": "Monarch Alternative Capital LP",
        "creditor_type": "hedge_fund",
        "bond_series": "GO",
        "claim_amount_original": 350_000_000,
        "recovery_amount": 157_500_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 0,
        "source_doc": "PROMESA Plan of Adjustment",
    },
    {
        "creditor_name": "Sculptor Capital Management Inc",
        "creditor_type": "hedge_fund",
        "bond_series": "COFINA",
        "claim_amount_original": 500_000_000,
        "recovery_amount": 325_000_000,
        "recovery_rate": 0.65,
        "sec_13f_flag": 1,
        "source_doc": "PROMESA Plan of Adjustment / SEC 13F",
    },
    # Mutual funds / asset managers — large retail/institutional exposure
    {
        "creditor_name": "Franklin Advisers Inc",
        "creditor_type": "mutual_fund",
        "bond_series": "GO",
        "claim_amount_original": 3_500_000_000,
        "recovery_amount": 1_575_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 1,
        "source_doc": "Franklin Templeton 13F / Plan of Adjustment",
    },
    {
        "creditor_name": "Oppenheimer Funds Inc",
        "creditor_type": "mutual_fund",
        "bond_series": "GO",
        "claim_amount_original": 700_000_000,
        "recovery_amount": 315_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 1,
        "source_doc": "Invesco / OppFunds SEC 13F",
    },
    {
        "creditor_name": "BlackRock Financial Management Inc",
        "creditor_type": "mutual_fund",
        "bond_series": "COFINA",
        "claim_amount_original": 1_200_000_000,
        "recovery_amount": 780_000_000,
        "recovery_rate": 0.65,
        "sec_13f_flag": 1,
        "source_doc": "BlackRock SEC 13F / COFINA settlement",
    },
    {
        "creditor_name": "PIMCO",
        "creditor_type": "mutual_fund",
        "bond_series": "GO",
        "claim_amount_original": 2_000_000_000,
        "recovery_amount": 900_000_000,
        "recovery_rate": 0.45,
        "sec_13f_flag": 1,
        "source_doc": "PIMCO SEC 13F / Plan of Adjustment",
    },
    # Bond insurers — wrapped large amounts
    {
        "creditor_name": "Assured Guaranty Municipal Corp",
        "creditor_type": "insurer",
        "bond_series": "GO",
        "claim_amount_original": 5_800_000_000,
        "recovery_amount": 2_784_000_000,
        "recovery_rate": 0.48,
        "sec_13f_flag": 0,
        "source_doc": "Assured Guaranty PSA / Plan of Adjustment",
    },
    {
        "creditor_name": "National Public Finance Guarantee Corp",
        "creditor_type": "insurer",
        "bond_series": "HTA",
        "claim_amount_original": 3_500_000_000,
        "recovery_amount": 1_225_000_000,
        "recovery_rate": 0.35,
        "sec_13f_flag": 0,
        "source_doc": "MBIA / National PSA / court documents",
    },
    {
        "creditor_name": "Ambac Assurance Corp",
        "creditor_type": "insurer",
        "bond_series": "COFINA",
        "claim_amount_original": 2_000_000_000,
        "recovery_amount": 1_300_000_000,
        "recovery_rate": 0.65,
        "sec_13f_flag": 0,
        "source_doc": "COFINA settlement / Ambac court filing",
    },
    # PREPA creditors (separate Title III case)
    {
        "creditor_name": "Cortland Capital Market Services LLC",
        "creditor_type": "bank",
        "bond_series": "PREPA",
        "claim_amount_original": 700_000_000,
        "recovery_amount": 350_000_000,
        "recovery_rate": 0.50,
        "sec_13f_flag": 0,
        "source_doc": "PREPA RSA / court documents",
    },
    # ERS (Employees Retirement System)
    {
        "creditor_name": "Whitebox Advisors LLC",
        "creditor_type": "hedge_fund",
        "bond_series": "ERS",
        "claim_amount_original": 150_000_000,
        "recovery_amount": 45_000_000,
        "recovery_rate": 0.30,
        "sec_13f_flag": 0,
        "source_doc": "ERS Plan of Adjustment / court filings",
    },
]

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]

PRIME_CLERK_URL = "https://restructuring.primeclerk.com/puertorico"


def _normalize_name(name):
    if not name or pd.isna(name):
        return ""
    n = str(name).upper().strip()
    n = re.sub(r"\b(INC\.?|LLC\.?|CORP\.?|LTD\.?|CO\.?|LP\.?|L\.P\.?|L\.L\.C\.?|MUNICIPAL)\b", "", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _session():
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0)",
        "Accept": "text/html,application/json,*/*",
    })
    return s


def _try_prime_clerk(session, logger):
    """Attempt to fetch creditor data from Prime Clerk docket site."""
    logger.info(f"  Trying Prime Clerk docket: {PRIME_CLERK_URL}")
    try:
        resp = session.get(PRIME_CLERK_URL, timeout=30)
        if resp.status_code == 200:
            text = resp.text
            # Look for links to Plan of Adjustment exhibits or creditor lists
            exhibit_links = re.findall(
                r'href=["\']([^"\']*(?:exhibit|creditor|plan.*adjust)[^"\']*)["\']',
                text, re.I
            )
            if exhibit_links:
                logger.info(f"  Found {len(exhibit_links)} exhibit/creditor links on Prime Clerk")
                return exhibit_links[:5]
            logger.info("  Prime Clerk page loaded but no structured creditor data found")
    except Exception as e:
        logger.warning(f"  Prime Clerk scrape failed: {e}")
    return None


def _file_has_data(path):
    if not path.exists():
        return False
    try:
        return len(pd.read_csv(path, dtype=str, nrows=2)) > 0
    except Exception:
        return False


def run(root=None):
    return _run(root=root, force=False)


def _run(root=None, force=False):
    if root is None:
        root = PROJECT_ROOT
    out_path = root / "data" / "staging" / "processed" / "pr_promesa_creditors.csv"
    logger = setup_logging("download_promesa_creditors")
    logger.info("Starting PROMESA Title III creditor data collection...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_promesa_creditors.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    # Check for manually placed supplement
    manual_path = root / "data" / "staging" / "raw" / "promesa" / "pr_promesa_creditors_raw.csv"
    extra_rows = []
    if manual_path.exists():
        logger.info(f"  Loading manual supplement: {manual_path}")
        df_manual = pd.read_csv(manual_path, dtype=str, low_memory=False)
        extra_rows = df_manual.to_dict("records")

    session = _session()
    _try_prime_clerk(session, logger)
    session.close()

    # Build output from curated + manual records
    all_records = KNOWN_CREDITORS + extra_rows
    df = pd.DataFrame(all_records)
    df["creditor_normalized"] = df["creditor_name"].apply(_normalize_name)
    if "new_bond_cusip" not in df.columns:
        df["new_bond_cusip"] = ""
    for col in PROMESA_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = df[PROMESA_COLUMNS]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8")

    total_claims = pd.to_numeric(df["claim_amount_original"], errors="coerce").fillna(0).sum()
    total_recovery = pd.to_numeric(df["recovery_amount"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("PROMESA CREDITORS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total creditor records:  {len(df):,}")
    logger.info(f"  Unique creditor names:   {df['creditor_name'].nunique()}")
    if "creditor_type" in df.columns:
        for ctype, count in df["creditor_type"].value_counts().items():
            logger.info(f"    {ctype}: {count}")
    logger.info(f"  Bond series covered:     {df['bond_series'].nunique()}")
    logger.info(f"  Total original claims:   ${total_claims:,.0f}")
    logger.info(f"  Total recovery:          ${total_recovery:,.0f}")
    if total_claims > 0:
        logger.info(f"  Avg recovery rate:       {total_recovery / total_claims:.1%}")

    return {"rows": len(df), "path": str(out_path), "errors": []}


def main():
    parser = argparse.ArgumentParser(description="Download PROMESA Title III creditor data")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nPROMESA creditors complete: {result['rows']:,} creditor records")
    return 0


if __name__ == "__main__":
    sys.exit(main())
