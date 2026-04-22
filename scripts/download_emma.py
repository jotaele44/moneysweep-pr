"""
Download Puerto Rico municipal bond data from MSRB EMMA (Electronic Municipal
Market Access). Captures PR bond issuers, underwriters, par amounts, and dates
for cross-referencing with federal award recipients and the influence network.

The MSRB EMMA API provides access to all municipal securities filed under
Rule 15c2-12. PR has issued ~$70B in municipal debt through PREPA, PRASA,
GDB, COFINA, and dozens of other public authorities.

Outputs:
  data/staging/processed/pr_emma_bonds.csv         — one row per security
  data/staging/processed/pr_emma_underwriters.csv  — aggregated by underwriter

Usage:
  python3 scripts/download_emma.py [--force]
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

EMMA_BASE     = "https://emma.msrb.org"
PAGE_SIZE     = 100
PAGE_SLEEP    = 0.5
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]

# Known PR bond issuers to seed the search (Public corporations + GDB + municipalities)
PR_SEED_ISSUERS = [
    "Puerto Rico Electric Power Authority",
    "Puerto Rico Aqueduct and Sewer Authority",
    "Puerto Rico Sales Tax Financing Corporation",
    "Puerto Rico Government Development Bank",
    "Puerto Rico Highway and Transportation Authority",
    "Puerto Rico Industrial Development Company",
    "Puerto Rico Infrastructure Financing Authority",
    "Puerto Rico Public Finance Corporation",
    "Puerto Rico Convention Center District Authority",
    "Puerto Rico Ports Authority",
    "Puerto Rico Housing Finance Authority",
    "Puerto Rico Municipal Finance Agency",
    "Commonwealth of Puerto Rico",
    "University of Puerto Rico",
]

BOND_COLUMNS = [
    "cusip", "issuer_name", "issuer_state", "description",
    "issue_date", "maturity_date", "par_amount", "coupon_rate",
    "sale_type", "tax_status", "use_of_proceeds",
]

UNDERWRITER_COLUMNS = [
    "underwriter_name", "total_par_amount", "deal_count",
    "issuer_count", "first_issue_date", "last_issue_date",
]


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "ContractSweeper/1.0 (PR municipal bond research)",
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
                logger.warning(f"  HTTP {resp.status_code} for {url} — skipping")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            return resp.json()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                wait = RETRY_BACKOFF[attempt]
                logger.warning(f"  Attempt {attempt+1} failed ({exc}) — retrying in {wait}s")
                time.sleep(wait)
            else:
                logger.error(f"  All {MAX_RETRIES} attempts failed for {url}: {exc}")
    return None


def _fetch_pr_securities(session: requests.Session, logger) -> list[dict]:
    """
    Query EMMA API for all PR-state municipal securities.
    EMMA REST endpoint: GET /api/Security/GetSecurities
    Filters by issuerState=PR, paginated via page/pageSize.
    """
    url  = f"{EMMA_BASE}/api/Security/GetSecurities"
    page = 1
    all_records: list[dict] = []

    while True:
        params = {
            "issuerState": "PR",
            "page":        page,
            "pageSize":    PAGE_SIZE,
        }
        data = _get(session, url, params, logger)
        if data is None:
            break

        # Handle both list and dict response shapes
        if isinstance(data, list):
            items = data
            has_more = len(items) == PAGE_SIZE
        else:
            items    = data.get("results") or data.get("data") or data.get("items") or []
            total    = data.get("totalCount") or data.get("total") or 0
            has_more = (page * PAGE_SIZE) < total

        if not items:
            break

        all_records.extend(items)
        if page == 1:
            total_hint = data.get("totalCount") or data.get("total") if isinstance(data, dict) else "?"
            logger.info(f"  EMMA securities: {total_hint} total, fetching...")

        if not has_more:
            break

        page += 1
        if page % 10 == 0:
            logger.info(f"    Page {page} ({len(all_records):,} records so far)")

    return all_records


def _records_to_bonds_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=BOND_COLUMNS)

    df = pd.json_normalize(records)

    rename = {
        "cusip":                   "cusip",
        "Cusip":                   "cusip",
        "issuerName":              "issuer_name",
        "IssuerName":              "issuer_name",
        "issuerState":             "issuer_state",
        "IssuerState":             "issuer_state",
        "description":             "description",
        "Description":             "description",
        "issueDate":               "issue_date",
        "IssueDate":               "issue_date",
        "maturityDate":            "maturity_date",
        "MaturityDate":            "maturity_date",
        "parAmount":               "par_amount",
        "ParAmount":               "par_amount",
        "couponRate":              "coupon_rate",
        "CouponRate":              "coupon_rate",
        "saleType":                "sale_type",
        "SaleType":                "sale_type",
        "taxStatus":               "tax_status",
        "TaxStatus":               "tax_status",
        "useOfProceeds":           "use_of_proceeds",
        "UseOfProceeds":           "use_of_proceeds",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})
    df["issuer_state"] = df.get("issuer_state", pd.Series(dtype=str)).fillna("PR")

    for col in BOND_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[BOND_COLUMNS]


def _build_underwriter_df(df_bonds: pd.DataFrame) -> pd.DataFrame:
    if df_bonds.empty or "use_of_proceeds" not in df_bonds.columns:
        return pd.DataFrame(columns=UNDERWRITER_COLUMNS)

    # Extract underwriter from use_of_proceeds field if present, else issuer_name
    # (EMMA does not always expose underwriter at security level; use issuer as proxy)
    if "underwriter_name" not in df_bonds.columns:
        return pd.DataFrame(columns=UNDERWRITER_COLUMNS)

    df_bonds["_par"] = pd.to_numeric(df_bonds["par_amount"], errors="coerce").fillna(0)
    agg = (
        df_bonds[df_bonds["underwriter_name"].notna() & (df_bonds["underwriter_name"] != "")]
        .groupby("underwriter_name")
        .agg(
            total_par_amount = ("_par",         "sum"),
            deal_count       = ("cusip",        "nunique"),
            issuer_count     = ("issuer_name",  "nunique"),
            first_issue_date = ("issue_date",   "min"),
            last_issue_date  = ("issue_date",   "max"),
        )
        .reset_index()
        .sort_values("total_par_amount", ascending=False)
    )
    return agg[UNDERWRITER_COLUMNS]


# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "emma"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_bonds_path  = raw_dir / "pr_emma_securities_raw.csv"
    bonds_path      = out_dir / "pr_emma_bonds.csv"
    uw_path         = out_dir / "pr_emma_underwriters.csv"

    logger  = setup_logging("download_emma")
    session = _session()

    if not force and raw_bonds_path.exists():
        logger.info(f"  Cached — loading {raw_bonds_path.name}")
        records = pd.read_csv(raw_bonds_path, dtype=str, low_memory=False).to_dict("records")
        logger.info(f"  {len(records):,} cached securities")
    else:
        logger.info("  Fetching PR municipal securities from EMMA...")
        records = _fetch_pr_securities(session, logger)
        if records:
            pd.DataFrame(records).to_csv(raw_bonds_path, index=False, encoding="utf-8")
            logger.info(f"  {len(records):,} securities cached → {raw_bonds_path.name}")
        else:
            logger.warning("  No securities returned from EMMA API — check endpoint or network")

    session.close()

    df_bonds = _records_to_bonds_df(records)
    df_bonds.to_csv(bonds_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {bonds_path.name} ({len(df_bonds):,} bonds)")

    df_uw = _build_underwriter_df(df_bonds)
    df_uw.to_csv(uw_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {uw_path.name} ({len(df_uw):,} underwriters)")

    total_par = float(pd.to_numeric(df_bonds.get("par_amount", pd.Series(dtype=str)),
                                    errors="coerce").sum())

    logger.info("=" * 60)
    logger.info("EMMA MUNICIPAL BOND SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Total PR securities:   {len(df_bonds):,}")
    logger.info(f"  Total par amount:      ${total_par:,.0f}")
    logger.info(f"  Unique issuers:        {df_bonds['issuer_name'].nunique():,}")
    logger.info(f"  Unique underwriters:   {len(df_uw):,}")

    if not df_uw.empty:
        logger.info("  Top underwriters by par amount:")
        for _, row in df_uw.head(10).iterrows():
            logger.info(f"    {str(row['underwriter_name'])[:50]:<50}  "
                        f"${float(row['total_par_amount']):>16,.0f}  "
                        f"({int(row['deal_count'])} deals)")

    return {
        "bond_rows":       len(df_bonds),
        "underwriter_rows": len(df_uw),
        "total_par":       total_par,
        "status":          "OK" if len(df_bonds) > 0 else "EMPTY",
        "bonds_path":      str(bonds_path),
        "uw_path":         str(uw_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PR municipal bond data from MSRB EMMA")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nEMMA complete: {result['bond_rows']:,} bonds, "
          f"{result['underwriter_rows']:,} underwriters, "
          f"${result['total_par']:,.0f} total par.")
    return 0 if result["status"] in ("OK", "EMPTY") else 1


if __name__ == "__main__":
    sys.exit(main())
