"""
Download FDIC bank institution profiles and financial history for Puerto Rico.

Uses the FDIC BankFind Suite API (banks.data.fdic.gov/api/).
No API key required.

Two datasets:
  1. Institutions — current profile of every FDIC-insured bank/thrift in PR
  2. Financials   — annual call-report summary for each institution (2000-present)

Output:
  data/staging/raw/fdic/pr_fdic_institutions.csv
  data/staging/raw/fdic/pr_fdic_financials.csv
  data/staging/processed/pr_fdic_institutions.csv
  data/staging/processed/pr_fdic_financials.csv

Usage:
  python3 scripts/download_fdic.py
  python3 scripts/download_fdic.py --force
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

FDIC_BASE    = "https://banks.data.fdic.gov/api"
PAGE_SLEEP   = 0.3
MAX_RETRIES  = 3
RETRY_BACKOFF = [5, 15, 30]

INSTITUTION_FIELDS = ",".join([
    "CERT", "NAME", "CITY", "STALP", "STNAME",
    "ACTIVE", "ESTYMD", "ENDEFYMD",
    "ASSET", "DEP", "LNLSNET", "SC", "NETINC",
    "RBCT1J", "ROA", "ROE",
    "INSTCAT", "SPECGRP", "CHARTER",
    "REPDTE", "HCTMULT",
])

FINANCIAL_FIELDS = ",".join([
    "CERT", "REPDTE", "REPYEAR",
    "ASSET", "DEP", "LNLSNET", "SC", "NETINC",
    "INTINC", "NONII", "NONIX",
    "RBCT1J", "ROA", "ROE",
    "LNLSDEPR", "NETCHARGE",
    "EQTOT", "LIABR",
])

INST_OUTPUT_COLUMNS = [
    "cert", "name", "city", "state", "active",
    "established_date", "end_date",
    "total_assets", "total_deposits", "net_loans",
    "securities", "net_income",
    "tier1_capital_ratio", "roa", "roe",
    "institution_category", "charter_type",
    "latest_report_date",
]

FIN_OUTPUT_COLUMNS = [
    "cert", "report_date", "report_year",
    "total_assets", "total_deposits", "net_loans",
    "securities", "net_income",
    "interest_income", "noninterest_income", "noninterest_expense",
    "tier1_capital_ratio", "roa", "roe",
    "loan_loss_provision", "net_chargeoffs",
    "total_equity", "total_liabilities",
]


# ---------------------------------------------------------------------------
# Network helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR banking research)",
        "Accept":     "application/json",
    })
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


def _paginate(session: requests.Session, endpoint: str, base_params: dict,
              data_key: str, logger) -> list[dict]:
    url     = f"{FDIC_BASE}/{endpoint}"
    offset  = 0
    limit   = 1000
    records = []

    while True:
        params = {**base_params, "limit": limit, "offset": offset}
        data   = _get(session, url, params, logger)
        if data is None:
            break
        batch = data.get("data") or []
        if not batch:
            break
        for item in batch:
            records.append(item.get("data", item))

        meta  = data.get("meta", {})
        total = meta.get("total", len(records))
        if offset == 0:
            logger.info(f"  FDIC {endpoint}: {total:,} total records")
        if offset + limit >= total:
            break
        offset += limit

    return records


# ---------------------------------------------------------------------------
# Institution download
# ---------------------------------------------------------------------------

def _download_institutions(session: requests.Session, logger) -> pd.DataFrame:
    logger.info("Fetching PR bank institution profiles...")
    records = _paginate(session, "institutions", {
        "filters": "STALP:PR",
        "fields":  INSTITUTION_FIELDS,
        "sort_by": "ASSET",
        "sort_order": "DESC",
    }, "data", logger)

    if not records:
        return pd.DataFrame(columns=INST_OUTPUT_COLUMNS)

    df = pd.DataFrame(records)

    rename = {
        "CERT":    "cert",
        "NAME":    "name",
        "CITY":    "city",
        "STALP":   "state",
        "ACTIVE":  "active",
        "ESTYMD":  "established_date",
        "ENDEFYMD": "end_date",
        "ASSET":   "total_assets",
        "DEP":     "total_deposits",
        "LNLSNET": "net_loans",
        "SC":      "securities",
        "NETINC":  "net_income",
        "RBCT1J":  "tier1_capital_ratio",
        "ROA":     "roa",
        "ROE":     "roe",
        "INSTCAT": "institution_category",
        "CHARTER": "charter_type",
        "REPDTE":  "latest_report_date",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for col in INST_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[INST_OUTPUT_COLUMNS]


# ---------------------------------------------------------------------------
# Financial history download
# ---------------------------------------------------------------------------

def _download_financials(session: requests.Session, certs: list[str], logger) -> pd.DataFrame:
    logger.info("Fetching PR bank financial history (call reports)...")

    # FDIC financials endpoint filters by STALP, not CERT list
    records = _paginate(session, "financials", {
        "filters":    "STALP:PR",
        "fields":     FINANCIAL_FIELDS,
        "sort_by":    "REPDTE",
        "sort_order": "DESC",
    }, "data", logger)

    if not records:
        return pd.DataFrame(columns=FIN_OUTPUT_COLUMNS)

    df = pd.DataFrame(records)

    rename = {
        "CERT":      "cert",
        "REPDTE":    "report_date",
        "REPYEAR":   "report_year",
        "ASSET":     "total_assets",
        "DEP":       "total_deposits",
        "LNLSNET":   "net_loans",
        "SC":        "securities",
        "NETINC":    "net_income",
        "INTINC":    "interest_income",
        "NONII":     "noninterest_income",
        "NONIX":     "noninterest_expense",
        "RBCT1J":    "tier1_capital_ratio",
        "ROA":       "roa",
        "ROE":       "roe",
        "LNLSDEPR":  "loan_loss_provision",
        "NETCHARGE":  "net_chargeoffs",
        "EQTOT":     "total_equity",
        "LIABR":     "total_liabilities",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    for col in FIN_OUTPUT_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df[FIN_OUTPUT_COLUMNS]


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "fdic"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    inst_raw_path = raw_dir / "pr_fdic_institutions.csv"
    fin_raw_path  = raw_dir / "pr_fdic_financials.csv"
    inst_out_path = out_dir / "pr_fdic_institutions.csv"
    fin_out_path  = out_dir / "pr_fdic_financials.csv"

    logger  = setup_logging("download_fdic")
    session = _session()

    # ------------------------------------------------------------------
    # Institutions
    # ------------------------------------------------------------------
    if not force and inst_raw_path.exists():
        logger.info(f"  Institution file exists — loading cached")
        df_inst = pd.read_csv(inst_raw_path, dtype=str, low_memory=False)
    else:
        df_inst = _download_institutions(session, logger)
        df_inst.to_csv(inst_raw_path, index=False, encoding="utf-8")

    certs = df_inst["cert"].dropna().tolist() if "cert" in df_inst.columns else []

    # ------------------------------------------------------------------
    # Financials
    # ------------------------------------------------------------------
    if not force and fin_raw_path.exists():
        logger.info(f"  Financials file exists — loading cached")
        df_fin = pd.read_csv(fin_raw_path, dtype=str, low_memory=False)
    else:
        df_fin = _download_financials(session, certs, logger)
        df_fin.to_csv(fin_raw_path, index=False, encoding="utf-8")

    session.close()

    df_inst.to_csv(inst_out_path, index=False, encoding="utf-8")
    df_fin.to_csv(fin_out_path,  index=False, encoding="utf-8")

    total_assets = pd.to_numeric(df_inst["total_assets"], errors="coerce").sum()
    active_count = (df_inst["active"] == "1").sum() if "active" in df_inst.columns else len(df_inst)

    logger.info("=" * 60)
    logger.info("FDIC BANK DATA SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Institutions (total/active): {len(df_inst):,} / {active_count:,}")
    logger.info(f"  Total assets (all):          ${total_assets / 1e9:.1f}B (thousands USD in raw)")
    logger.info(f"  Financial report rows:       {len(df_fin):,}")
    logger.info(f"  Written: {inst_out_path.name}, {fin_out_path.name}")

    if not df_inst.empty:
        logger.info(f"\n  Institutions by total assets:")
        for _, row in df_inst.head(10).iterrows():
            assets = row.get("total_assets", "")
            assets_str = f"${float(assets) / 1e6:>8,.0f}M" if assets not in ("", None) else "      N/A "
            status = "ACTIVE" if str(row.get("active")) == "1" else "closed"
            logger.info(f"    {str(row.get('name', ''))[:50]:<50} {assets_str}  [{status}]")

    return {
        "institution_rows": len(df_inst),
        "financial_rows":   len(df_fin),
        "status":           "OK" if len(df_inst) > 0 else "EMPTY",
        "inst_path":        str(inst_out_path),
        "fin_path":         str(fin_out_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download FDIC bank data for Puerto Rico")
    parser.add_argument("--force", action="store_true", help="Re-download even if files exist")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nFDIC download complete. {result['institution_rows']:,} institutions, "
          f"{result['financial_rows']:,} financial report rows.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
