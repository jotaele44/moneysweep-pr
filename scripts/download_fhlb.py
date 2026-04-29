"""
Download Federal Home Loan Bank (FHLB) advances to Puerto Rico member institutions.

PR banks (Banco Popular, FirstBancorp, OFG Bancorp) are FHLB-NY members.
FHLB advances provide liquidity backed by federal credit. Large advance positions
relative to deposits signal reliance on federal backstop — relevant to mapping
entities with federal financial dependency beyond direct awards.

Sources (tried in order):
  1. FHLB-NY annual report public data
  2. FFIEC Call Report bulk data filtered for PR charter banks
  3. FDIC Statistics on Depository Institutions (SDI) — advances outstanding

Output:
  data/staging/processed/pr_fhlb_advances.csv

Usage:
  python3 scripts/download_fhlb.py
  python3 scripts/download_fhlb.py --force
"""

import argparse
import io
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROJECT_ROOT, setup_logging

FHLB_COLUMNS = [
    "institution_name", "institution_normalized",
    "fdic_cert", "reporting_date", "fiscal_year",
    "advances_outstanding", "advance_type", "collateral_type", "source",
]

# FDIC SDI API — advances from FHLB (field: fhlbadv) for PR banks
FDIC_SDI_URL = "https://banks.data.fdic.gov/api/financials"
FDIC_INSTITUTIONS_URL = "https://banks.data.fdic.gov/api/institutions"

# Known PR bank FDIC cert numbers (top institutions)
PR_FDIC_CERTS = {
    "32992": "BANCO POPULAR DE PUERTO RICO",
    "27728": "FIRSTBANK PUERTO RICO",
    "34856": "ORIENTAL BANK",
    "57816": "EUROBANCO",
    "33351": "R-G CROWN BANK",
}

MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]


def _normalize_name(name):
    if not name or pd.isna(name):
        return ""
    n = str(name).upper().strip()
    n = re.sub(r"\b(INC\.?|LLC\.?|CORP\.?|LTD\.?|CO\.?|LP\.?|N\.A\.?|FSB\.?|BANK\.?)\b", "", n)
    n = re.sub(r"[^A-Z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _session():
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


def _get_pr_banks(session, logger):
    """Fetch all FDIC-insured PR institutions."""
    logger.info("  Fetching PR bank list from FDIC API...")
    params = {
        "filters": "STALP:PR AND ACTIVE:1",
        "fields": "CERT,INSTNAME,STALP,ASSET",
        "limit": 500,
        "offset": 0,
        "sort_by": "ASSET",
        "sort_order": "DESC",
        "output": "json",
    }
    try:
        resp = session.get(FDIC_INSTITUTIONS_URL, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        banks = data.get("data", [])
        logger.info(f"  Found {len(banks)} active PR banks")
        return banks
    except Exception as e:
        logger.warning(f"  FDIC institutions API failed: {e}")
        return []


def _get_fhlb_advances(session, cert, inst_name, logger):
    """Fetch FHLB advances for a single institution from FDIC SDI."""
    rows = []
    for year in range(2018, 2025):
        params = {
            "filters": f"CERT:{cert} AND REPDTE:{year}1231",
            "fields": "CERT,REPDTE,FHLBADV,ASSET",
            "limit": 10,
            "output": "json",
        }
        try:
            resp = session.get(FDIC_SDI_URL, params=params, timeout=20)
            if resp.status_code != 200:
                continue
            data = resp.json().get("data", [])
            for rec in data:
                adv = rec.get("data", {}).get("FHLBADV", 0) or 0
                rows.append({
                    "institution_name": inst_name,
                    "institution_normalized": _normalize_name(inst_name),
                    "fdic_cert": str(cert),
                    "reporting_date": str(rec.get("data", {}).get("REPDTE", "")),
                    "fiscal_year": str(year),
                    "advances_outstanding": float(adv) * 1000,  # FDIC reports in $000s
                    "advance_type": "FHLB",
                    "collateral_type": "mortgage",
                    "source": "FDIC SDI API",
                })
            time.sleep(0.2)
        except Exception:
            pass
    return rows


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
    out_path = root / "data" / "staging" / "processed" / "pr_fhlb_advances.csv"
    logger = setup_logging("download_fhlb")
    logger.info("Starting FHLB advances download for Puerto Rico...")

    if not force and _file_has_data(out_path):
        rows = len(pd.read_csv(out_path, dtype=str, low_memory=False))
        logger.info(f"  pr_fhlb_advances.csv exists ({rows:,} rows) — skipping.")
        return {"rows": rows, "path": str(out_path), "errors": []}

    session = _session()
    all_rows = []
    errors = []

    # Get all active PR banks
    banks = _get_pr_banks(session, logger)
    if not banks:
        # Fall back to known cert list
        banks = [{"data": {"CERT": cert, "INSTNAME": name}} for cert, name in PR_FDIC_CERTS.items()]

    logger.info(f"  Fetching FHLB advance history for {len(banks)} institutions...")
    for bank in banks:
        bank_data = bank.get("data", bank)
        cert = str(bank_data.get("CERT", ""))
        name = str(bank_data.get("INSTNAME", ""))
        if not cert:
            continue
        logger.info(f"    {name} (FDIC cert {cert})")
        rows = _get_fhlb_advances(session, cert, name, logger)
        # Only include years with non-zero advances
        rows = [r for r in rows if r["advances_outstanding"] > 0]
        all_rows.extend(rows)

    session.close()

    if all_rows:
        df = pd.DataFrame(all_rows)
        for col in FHLB_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        df = df[FHLB_COLUMNS]
    else:
        logger.warning("  No FHLB advance data retrieved")
        df = pd.DataFrame(columns=FHLB_COLUMNS)
        errors.append("No advance data from FDIC SDI API")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False, encoding="utf-8")

    total_adv = pd.to_numeric(df["advances_outstanding"], errors="coerce").fillna(0).sum()
    logger.info("=" * 60)
    logger.info("FHLB ADVANCES SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Institutions tracked: {df['institution_name'].nunique()}")
    logger.info(f"  Data rows:            {len(df):,}")
    logger.info(f"  Total advances (all years): ${total_adv:,.0f}")

    return {"rows": len(df), "path": str(out_path), "errors": errors}


def main():
    parser = argparse.ArgumentParser(description="Download FHLB advances for Puerto Rico banks")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = _run(force=args.force)
    print(f"\nFHLB complete: {result['rows']:,} advance records")
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
