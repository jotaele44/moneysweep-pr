"""
Download Puerto Rico municipal bond data from MSRB EMMA (Electronic Municipal
Market Access). Captures PR bond issuers, underwriters, par amounts, and dates
for cross-referencing with federal award recipients and the influence network.

PR has issued ~$70B in municipal debt through PREPA, PRASA, GDB, COFINA, and
dozens of other public authorities.

The MSRB REST API at /api/Security/GetSecurities now requires authentication.
This script tries three alternative paths in order:
  Path A: EMMA IssuerHomePage XHR endpoint (no auth required)
  Path B: MSRB underwriter-statistics endpoint (aggregated, no auth)
  Path C: MSRB bulk disclosure export for state PR (zipped CSV)

Outputs:
  data/staging/processed/pr_emma_bonds.csv         — one row per security
  data/staging/processed/pr_emma_underwriters.csv  — aggregated by underwriter

Usage:
  python3 scripts/download_emma.py [--force]
"""

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMMA_BASE     = "https://emma.msrb.org"
PAGE_SIZE     = 500
PAGE_SLEEP    = 0.5
MAX_RETRIES   = 3
RETRY_BACKOFF = [5, 15, 30]

# Path A — XHR endpoint behind the EMMA state-issuer search page
EMMA_ISSUER_PAGE_ENDPOINT = "/IssuerHomePage/GetSecurities"

# Path B — MSRB underwriter statistics by state (no auth, returns aggregates)
EMMA_UNDERWRITER_STAT_ENDPOINTS = [
    "/api/Statistics/GetUnderwritersByState",
    "/api/Issuance/GetUnderwritersByState",
]

# Path C — Bulk security disclosure export
EMMA_BULK_ENDPOINTS = [
    "/BulkDownload/GetBulkDisclosuresForState",
    "/Content/BulkDownloads/PR_Securities.zip",
]

# Known PR bond issuers to seed issuer-level queries
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
    "cusip", "issuer_name", "issuer_normalized",
    "underwriter_name", "underwriter_normalized",
    "issuer_state", "description",
    "issue_date", "maturity_date", "par_amount", "coupon_rate",
    "sale_type", "tax_status", "use_of_proceeds",
]

UNDERWRITER_COLUMNS = [
    "underwriter_name", "underwriter_normalized",
    "total_par_amount", "deal_count",
    "issuer_count", "first_issue_date", "last_issue_date",
]

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ContractSweeper/1.0; PR bond research)",
        "Accept":     "application/json, text/html, */*",
        "Referer":    EMMA_BASE,
    })
    return s


def _get_json(session: requests.Session, url: str, params: dict, logger):
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited — sleeping 60s")
                time.sleep(60)
                continue
            if 400 <= resp.status_code < 500:
                logger.debug(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            time.sleep(PAGE_SLEEP)
            try:
                return resp.json()
            except ValueError:
                return None
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.debug(f"  Request failed: {exc}")
    return None


def _get_bytes(session: requests.Session, url: str, params: dict, logger) -> bytes | None:
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=120, stream=True)
            if 400 <= resp.status_code < 500:
                logger.debug(f"  HTTP {resp.status_code} for {url}")
                return None
            resp.raise_for_status()
            buf = io.BytesIO()
            for chunk in resp.iter_content(chunk_size=1024 * 512):
                buf.write(chunk)
            return buf.getvalue()
        except requests.RequestException as exc:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
            else:
                logger.debug(f"  Request failed: {exc}")
    return None


# ---------------------------------------------------------------------------
# Path A — EMMA IssuerHomePage XHR
# ---------------------------------------------------------------------------

def _fetch_path_a(session: requests.Session, logger) -> list[dict]:
    url = EMMA_BASE + EMMA_ISSUER_PAGE_ENDPOINT
    all_records: list[dict] = []
    page = 1
    logger.info(f"  Path A: {EMMA_ISSUER_PAGE_ENDPOINT}")
    while True:
        data = _get_json(session, url, {
            "stateCode": "PR",
            "page":       page,
            "pageSize":   PAGE_SIZE,
        }, logger)
        if data is None:
            break
        if isinstance(data, list):
            items = data
            has_more = len(items) == PAGE_SIZE
        elif isinstance(data, dict):
            items = (data.get("securities") or data.get("results") or
                     data.get("data") or data.get("items") or [])
            total = int(data.get("totalCount") or data.get("total") or 0)
            has_more = total > page * PAGE_SIZE
        else:
            break
        if not items:
            break
        all_records.extend(items)
        if page == 1:
            logger.info(f"    Fetching PR securities (page {page})...")
        if not has_more:
            break
        page += 1
        if page % 5 == 0:
            logger.info(f"    Page {page}, {len(all_records):,} records so far")
    return all_records


# ---------------------------------------------------------------------------
# Path B — MSRB underwriter statistics by state
# ---------------------------------------------------------------------------

def _fetch_path_b(session: requests.Session, logger) -> list[dict]:
    for ep in EMMA_UNDERWRITER_STAT_ENDPOINTS:
        url = EMMA_BASE + ep
        logger.info(f"  Path B: {ep}")
        data = _get_json(session, url, {"stateCode": "PR", "state": "PR"}, logger)
        if data is None:
            continue
        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = (data.get("underwriters") or data.get("results") or
                       data.get("data") or [])
        else:
            records = []
        if records:
            logger.info(f"    Path B: {len(records):,} underwriter records")
            return records
    return []


# ---------------------------------------------------------------------------
# Path C — Bulk disclosure export (zipped CSV)
# ---------------------------------------------------------------------------

def _fetch_path_c(session: requests.Session, logger) -> list[dict]:
    for ep in EMMA_BULK_ENDPOINTS:
        url = EMMA_BASE + ep if not ep.startswith("http") else ep
        logger.info(f"  Path C: {ep}")
        raw = _get_bytes(session, url, {"state": "PR"}, logger)
        if raw is None:
            continue
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if not csv_names:
                    continue
                target = next((n for n in csv_names if "securit" in n.lower()), csv_names[0])
                with zf.open(target) as f:
                    df = pd.read_csv(f, dtype=str, low_memory=False)
            records = df.to_dict("records")
            if records:
                logger.info(f"    Path C: {len(records):,} records from ZIP")
                return records
        except (zipfile.BadZipFile, Exception) as exc:
            logger.debug(f"    Path C ZIP error: {exc}")
            # Try as plain JSON bytes
            try:
                records = json.loads(raw.decode("utf-8"))
                if records:
                    return records
            except Exception:
                pass
    return []


# ---------------------------------------------------------------------------
# Transform raw records → canonical DataFrame
# ---------------------------------------------------------------------------

_RENAME_MAP = {
    # CUSIP
    "cusip": "cusip", "Cusip": "cusip", "CUSIP": "cusip",
    # Issuer
    "issuerName": "issuer_name", "IssuerName": "issuer_name",
    "issuer_name": "issuer_name", "issuerStateName": "issuer_name",
    # Underwriter  — EMMA uses syndicateManager or underwriterName
    "syndicateManager": "underwriter_name", "SyndicateManager": "underwriter_name",
    "underwriterName": "underwriter_name", "UnderwriterName": "underwriter_name",
    "underwriter": "underwriter_name", "Underwriter": "underwriter_name",
    # State
    "issuerState": "issuer_state", "IssuerState": "issuer_state",
    "stateCode": "issuer_state",
    # Description
    "description": "description", "Description": "description",
    "securityDescription": "description",
    # Dates
    "issueDate": "issue_date", "IssueDate": "issue_date",
    "datedDate": "issue_date",
    "maturityDate": "maturity_date", "MaturityDate": "maturity_date",
    # Par
    "parAmount": "par_amount", "ParAmount": "par_amount",
    "originalParAmount": "par_amount",
    # Coupon
    "couponRate": "coupon_rate", "CouponRate": "coupon_rate",
    "interestRate": "coupon_rate",
    # Sale type
    "saleType": "sale_type", "SaleType": "sale_type",
    # Tax status
    "taxStatus": "tax_status", "TaxStatus": "tax_status",
    "taxDesignation": "tax_status",
    # Use of proceeds
    "useOfProceeds": "use_of_proceeds", "UseOfProceeds": "use_of_proceeds",
    "purposeCode": "use_of_proceeds",
}


def _records_to_bonds_df(records: list[dict]) -> pd.DataFrame:
    if not records:
        return pd.DataFrame(columns=BOND_COLUMNS)

    df = pd.json_normalize(records)
    df = df.rename(columns={k: v for k, v in _RENAME_MAP.items() if k in df.columns})

    df["issuer_state"] = df.get("issuer_state", pd.Series(dtype=str)).fillna("PR")

    # Populate normalized columns
    for raw_col, norm_col in [("issuer_name", "issuer_normalized"),
                               ("underwriter_name", "underwriter_normalized")]:
        if raw_col in df.columns:
            df[norm_col] = df[raw_col].fillna("").apply(_normalize_name)
        else:
            df[raw_col] = ""
            df[norm_col] = ""

    for col in BOND_COLUMNS:
        if col not in df.columns:
            df[col] = ""

    return df[BOND_COLUMNS].copy()


def _records_to_underwriter_df(records: list[dict]) -> pd.DataFrame:
    """Build underwriter aggregates from Path B underwriter-stats records."""
    if not records:
        return pd.DataFrame(columns=UNDERWRITER_COLUMNS)

    rows = []
    for r in records:
        def _f(*keys):
            for k in keys:
                v = r.get(k) or r.get(k.lower())
                if v is not None:
                    return str(v).strip()
            return ""

        name = _f("underwriterName", "UnderwriterName", "name", "Name",
                  "underwriter_name", "underwriter")
        par_raw = _f("totalParAmount", "TotalParAmount", "total_par_amount",
                     "parAmount", "totalPar")
        try:
            par = float(str(par_raw).replace(",", "").replace("$", "")) if par_raw else 0.0
        except ValueError:
            par = 0.0

        rows.append({
            "underwriter_name":       name,
            "underwriter_normalized": _normalize_name(name),
            "total_par_amount":       par,
            "deal_count":             int(_f("dealCount", "deal_count", "numberOfDeals") or 0),
            "issuer_count":           int(_f("issuerCount", "issuer_count", "numberOfIssuers") or 0),
            "first_issue_date":       _f("firstIssueDate", "first_issue_date", "firstDate"),
            "last_issue_date":        _f("lastIssueDate", "last_issue_date", "lastDate"),
        })

    df = pd.DataFrame(rows, columns=UNDERWRITER_COLUMNS)
    df = df[df["underwriter_name"] != ""].sort_values("total_par_amount", ascending=False)
    return df


def _build_underwriter_df_from_bonds(df_bonds: pd.DataFrame) -> pd.DataFrame:
    """Aggregate underwriter stats from bond-level data when underwriter_name is present."""
    if df_bonds.empty or "underwriter_name" not in df_bonds.columns:
        return pd.DataFrame(columns=UNDERWRITER_COLUMNS)

    valid = df_bonds[
        df_bonds["underwriter_name"].notna() & (df_bonds["underwriter_name"] != "")
    ].copy()
    if valid.empty:
        return pd.DataFrame(columns=UNDERWRITER_COLUMNS)

    valid["_par"] = pd.to_numeric(valid["par_amount"], errors="coerce").fillna(0)
    agg = (
        valid.groupby(["underwriter_name", "underwriter_normalized"])
        .agg(
            total_par_amount = ("_par",          "sum"),
            deal_count       = ("cusip",         "nunique"),
            issuer_count     = ("issuer_name",   "nunique"),
            first_issue_date = ("issue_date",    "min"),
            last_issue_date  = ("issue_date",    "max"),
        )
        .reset_index()
        .sort_values("total_par_amount", ascending=False)
    )
    return agg[UNDERWRITER_COLUMNS]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT

    root    = Path(root)
    raw_dir = root / "data" / "staging" / "raw" / "emma"
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_dir = root / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw_bonds_path = raw_dir / "pr_emma_securities_raw.csv"
    bonds_path     = out_dir / "pr_emma_bonds.csv"
    uw_path        = out_dir / "pr_emma_underwriters.csv"

    logger  = setup_logging("download_emma", log_dir=root / "data" / "logs")
    session = _session()

    bond_records:  list[dict] = []
    uw_records:    list[dict] = []

    if not force and raw_bonds_path.exists():
        logger.info(f"  Cached — loading {raw_bonds_path.name}")
        bond_records = pd.read_csv(raw_bonds_path, dtype=str, low_memory=False).to_dict("records")
        logger.info(f"  {len(bond_records):,} cached securities")
    else:
        logger.info("  Fetching PR securities from EMMA (Path A: IssuerHomePage XHR)...")
        bond_records = _fetch_path_a(session, logger)

        if not bond_records:
            logger.info("  Path A returned nothing — trying Path B (underwriter stats)...")
            uw_records = _fetch_path_b(session, logger)

        if not bond_records and not uw_records:
            logger.info("  Path B returned nothing — trying Path C (bulk disclosure ZIP)...")
            bond_records = _fetch_path_c(session, logger)

        if bond_records:
            pd.DataFrame(bond_records).to_csv(raw_bonds_path, index=False, encoding="utf-8")
            logger.info(f"  {len(bond_records):,} securities cached → {raw_bonds_path.name}")
        elif not uw_records:
            logger.warning(
                "  EMMA: no data retrieved from any path.\n"
                "  Manual option: visit https://emma.msrb.org and search for issuer state 'PR',\n"
                "  then export to CSV and save as data/staging/raw/emma/pr_emma_securities_raw.csv"
            )

    session.close()

    # Build bond and underwriter DataFrames
    df_bonds = _records_to_bonds_df(bond_records)
    df_bonds.to_csv(bonds_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {bonds_path.name} ({len(df_bonds):,} bonds)")

    # Prefer Path B stats if we have them; fall back to aggregation from bond rows
    if uw_records:
        df_uw = _records_to_underwriter_df(uw_records)
    else:
        df_uw = _build_underwriter_df_from_bonds(df_bonds)

    df_uw.to_csv(uw_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {uw_path.name} ({len(df_uw):,} underwriters)")

    total_par = float(pd.to_numeric(df_bonds["par_amount"], errors="coerce").sum())

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
            logger.info(
                f"    {str(row['underwriter_name'])[:50]:<50}  "
                f"${float(row['total_par_amount']):>16,.0f}  "
                f"({int(row['deal_count'])} deals)"
            )

    return {
        "bond_rows":        len(df_bonds),
        "underwriter_rows": len(df_uw),
        "total_par":        total_par,
        "status":           "OK" if (len(df_bonds) > 0 or len(df_uw) > 0) else "EMPTY",
        "bonds_path":       str(bonds_path),
        "uw_path":          str(uw_path),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

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
