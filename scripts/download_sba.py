"""
Download SBA Disaster Loan data for Puerto Rico from data.sba.gov CKAN API.

Step 1: Discover the CSV resource ID from the 'disaster-loan-data' package.
Step 2: Paginate the CKAN datastore_search endpoint filtered to State=PR.
Step 3: Fall back to a direct CSV dump URL if the datastore API fails.

Output:
  data/staging/raw/sba/sba_disaster_loans_pr.csv     (raw)
  data/staging/processed/pr_sba_loans_master.csv     (canonical master)

Usage:
  python3 scripts/download_sba.py            # full run
  python3 scripts/download_sba.py --force    # re-download even if file exists
"""

import argparse
import json
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

CKAN_PACKAGE_URL = "https://data.sba.gov/api/3/action/package_show"
CKAN_DATASTORE_URL = "https://data.sba.gov/api/3/action/datastore_search"
CKAN_DUMP_URL_TEMPLATE = (
    "https://data.sba.gov/datastore/dump/{resource_id}"
    "?bom=true&filters=%7B%22State%22%3A%22PR%22%7D"
)

PACKAGE_ID = "disaster-loan-data"
PAGE_SIZE = 1000
PAGE_SLEEP = 0.3
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]

PR_STATE_VALUES = {"pr", "puerto rico", "72"}

MASTER_COLUMNS = [
    "award_id",
    "recipient_name",
    "recipient_uei",
    "awarding_agency",
    "awarding_sub_agency",
    "obligated_amount",
    "award_date",
    "fiscal_year",
    "pop_state",
    "pop_county",
    "description",
    "source_file",
    "source_dataset",
    "award_category",
]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Accept": "application/json"})
    return s


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _derive_fiscal_year(date_str) -> str:
    """Derive US fiscal year from a date string. Oct-Dec → year+1."""
    if not date_str or pd.isna(date_str):
        return ""
    try:
        d = pd.to_datetime(str(date_str), errors="coerce")
        if pd.isna(d):
            return ""
        return str(d.year + 1) if d.month >= 10 else str(d.year)
    except Exception:
        return ""


def _get(session: requests.Session, url: str, params: dict, logger) -> dict | None:
    """GET with retry/backoff. Returns parsed JSON or None."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited (429) — sleeping 30s then retrying")
                time.sleep(30)
                resp = session.get(url, params=params, timeout=60)
            if 400 <= resp.status_code < 500:
                logger.error(f"  HTTP {resp.status_code} — skipping: {resp.text[:300]}")
                return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
        if attempt < MAX_RETRIES - 1:
            wait = RETRY_BACKOFF[attempt]
            logger.warning(f"  Attempt {attempt + 1} failed ({last_err}) — retrying in {wait}s")
            time.sleep(wait)
    logger.error(f"  All {MAX_RETRIES} attempts failed: {last_err}")
    return None


def _find_resource_id(session: requests.Session, logger) -> str | None:
    """
    Call CKAN package_show and return the resource ID for the disaster loan CSV.
    Prefers a resource whose name contains 'Business'; otherwise takes the first CSV.
    """
    logger.info(f"  Fetching CKAN package metadata: {PACKAGE_ID}")
    data = _get(session, CKAN_PACKAGE_URL, {"id": PACKAGE_ID}, logger)
    if not data:
        logger.warning("  CKAN package_show returned no data")
        return None

    if not data.get("success"):
        logger.warning(f"  CKAN package_show success=False: {data.get('error')}")
        return None

    resources = data.get("result", {}).get("resources", [])
    if not resources:
        logger.warning("  No resources found in CKAN package")
        return None

    csv_resources = [r for r in resources if r.get("format", "").upper() == "CSV"]
    if not csv_resources:
        logger.warning("  No CSV resources found — trying all resources")
        csv_resources = resources

    # Prefer resource with 'Business' in the name
    for r in csv_resources:
        if "business" in r.get("name", "").lower():
            logger.info(f"  Selected resource '{r['name']}' (id={r['id']})")
            return r["id"]

    # Fall back to the first CSV resource
    r = csv_resources[0]
    logger.info(f"  Selected first CSV resource '{r.get('name', '')}' (id={r['id']})")
    return r["id"]


def _paginate_datastore(
    session: requests.Session,
    resource_id: str,
    logger,
) -> list[dict]:
    """Paginate CKAN datastore_search filtered to State=PR."""
    all_records = []
    offset = 0
    total = None
    filters = json.dumps({"State": "PR"})

    while True:
        params = {
            "resource_id": resource_id,
            "filters": filters,
            "limit": PAGE_SIZE,
            "offset": offset,
        }
        data = _get(session, CKAN_DATASTORE_URL, params, logger)
        if data is None:
            logger.error("  CKAN datastore_search failed — aborting pagination")
            return all_records

        if not data.get("success"):
            logger.error(f"  CKAN datastore_search success=False: {data.get('error')}")
            return all_records

        result = data.get("result", {})
        if total is None:
            total = result.get("total", 0)
            logger.info(f"  Total records for PR: {total:,}")

        records = result.get("records", [])
        if not records:
            break

        all_records.extend(records)

        if len(all_records) % 5000 == 0:
            logger.info(f"  Fetched {len(all_records):,} / {total:,} records")

        offset += PAGE_SIZE
        if offset >= total:
            break

        time.sleep(PAGE_SLEEP)

    return all_records


def _try_direct_csv(
    session: requests.Session,
    resource_id: str,
    raw_path: Path,
    logger,
) -> pd.DataFrame | None:
    """Attempt direct CSV dump download. Returns DataFrame or None."""
    url = CKAN_DUMP_URL_TEMPLATE.format(resource_id=resource_id)
    logger.warning(f"  Trying direct CSV dump: {url}")
    try:
        resp = session.get(url, timeout=120, stream=True)
        if resp.status_code != 200:
            logger.warning(f"  Direct dump returned HTTP {resp.status_code}")
            return None
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        with open(raw_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                f.write(chunk)
        df = pd.read_csv(raw_path, dtype=str, low_memory=False, encoding="utf-8-sig")
        logger.info(f"  Direct CSV dump: {len(df):,} rows")
        return df
    except Exception as e:
        logger.warning(f"  Direct CSV dump failed: {e}")
        return None


def _records_to_df(records: list[dict], source_file: str) -> pd.DataFrame:
    """Map raw SBA CKAN records to canonical master columns."""
    if not records:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    df = pd.DataFrame(records)

    # Remove CKAN internal _id column if present
    df = df.drop(columns=["_id"], errors="ignore")

    # ----- Field mapping (try multiple name variants) -----
    def col(df, *candidates):
        """Return first matching column value Series, or empty string Series."""
        for c in candidates:
            if c in df.columns:
                return df[c]
        return pd.Series("", index=df.index)

    state_series = col(df, "State", "state", "BorrowerState")
    mask = state_series.str.strip().str.upper().isin({"PR", "PUERTO RICO", "72"})
    df = df[mask].copy()

    if df.empty:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    # award_id: prefer ApplicationNumber → LoanNumber → index
    app_num = col(df, "ApplicationNumber", "AppNumber", "LoanNumber", "LoanApplicationNumber")
    df["award_id"] = "SBA-" + app_num.where(
        app_num.str.strip() != "", other=df.reset_index(drop=True).index.astype(str)
    ).astype(str).str.strip()

    df["recipient_name"] = col(df, "BorrowerName", "BusinessName", "RecipientName", "borrower_name")
    df["recipient_uei"] = ""
    df["awarding_agency"] = "Small Business Administration"
    df["awarding_sub_agency"] = ""
    df["obligated_amount"] = col(df, "LoanAmount", "ApprovedAmount", "GrossApproval", "LoanApprovedAmount")
    df["award_date"] = col(df, "DateApproved", "LoanApprovedDate", "ApprovalDate", "date_approved")
    df["fiscal_year"] = df["award_date"].apply(_derive_fiscal_year)
    df["pop_state"] = col(df, "State", "state", "BorrowerState")
    df["pop_county"] = col(df, "County", "BorrowerCounty", "county")
    df["description"] = col(df, "DisasterName", "DisasterNumber", "disaster_name", "DisasterType")
    df["source_file"] = source_file
    df["source_dataset"] = "sba_loans"
    df["award_category"] = "loan"

    for c in MASTER_COLUMNS:
        if c not in df.columns:
            df[c] = ""

    return df[MASTER_COLUMNS]


def _csv_to_master(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """Map a raw CSV DataFrame (from direct dump) to canonical master columns."""
    return _records_to_df(df.to_dict("records"), source_file)


def _file_has_data(filepath: Path) -> bool:
    """Return True if file exists and has at least one data row."""
    if not filepath.exists():
        return False
    try:
        df = pd.read_csv(filepath, dtype=str, nrows=2, low_memory=False)
        return len(df) > 0
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

def run(root: Path = None) -> dict:
    """Main entry point (no --force). Returns summary dict."""
    return _run(root=root, force=False)


def _run(root: Path = None, force: bool = False) -> dict:
    """Internal runner used by both run() and main()."""
    if root is None:
        root = PROJECT_ROOT

    raw_dir = root / "data" / "staging" / "raw" / "sba"
    raw_path = raw_dir / "sba_disaster_loans_pr.csv"
    master_path = root / "data" / "staging" / "processed" / "pr_sba_loans_master.csv"

    raw_dir.mkdir(parents=True, exist_ok=True)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_sba")
    logger.info("Starting SBA Disaster Loan download for Puerto Rico...")

    # ------------------------------------------------------------------
    # Skip if already downloaded and not forcing
    # ------------------------------------------------------------------
    if not force and _file_has_data(raw_path):
        logger.info(f"  Raw file already exists ({raw_path.name}) — loading for master build")
        try:
            df_raw = pd.read_csv(raw_path, dtype=str, low_memory=False)
        except Exception as e:
            logger.error(f"  Could not read existing raw file: {e}")
            df_raw = pd.DataFrame()
    else:
        # ------------------------------------------------------------------
        # Step 1: Discover resource ID
        # ------------------------------------------------------------------
        session = _session()
        resource_id = _find_resource_id(session, logger)

        df_raw = None

        if resource_id:
            # Step 2: Paginate CKAN datastore
            logger.info("  Paginating CKAN datastore (State=PR)...")
            records = _paginate_datastore(session, resource_id, logger)

            if records:
                df_raw = pd.DataFrame(records).drop(columns=["_id"], errors="ignore")
                raw_dir.mkdir(parents=True, exist_ok=True)
                df_raw.to_csv(raw_path, index=False, encoding="utf-8")
                logger.info(f"  Saved {len(df_raw):,} raw rows → {raw_path.name}")
            else:
                logger.warning("  Datastore returned 0 records — trying direct CSV dump")
                df_raw = _try_direct_csv(session, resource_id, raw_path, logger)

        else:
            logger.warning("  Could not determine resource ID — skipping CKAN steps")

        # ------------------------------------------------------------------
        # Fallback: if no data yet
        # ------------------------------------------------------------------
        if df_raw is None or (hasattr(df_raw, "__len__") and len(df_raw) == 0):
            logger.warning(
                "  CKAN API failed to return data. Manual download may be required. "
                "Visit https://data.sba.gov/dataset/disaster-loan-data and download the "
                "Business disaster loans CSV, then save to data/staging/raw/sba/sba_disaster_loans_pr.csv"
            )
            df_raw = pd.DataFrame()

        session.close()

    # ------------------------------------------------------------------
    # Build master
    # ------------------------------------------------------------------
    logger.info("Building SBA loans master...")

    if df_raw is None or len(df_raw) == 0:
        logger.warning("  No data to process — writing empty master with headers")
        master = pd.DataFrame(columns=MASTER_COLUMNS)
    else:
        master = _csv_to_master(df_raw, raw_path.name)

    master_path.parent.mkdir(parents=True, exist_ok=True)
    master.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(master):,} rows → {master_path.name}")

    summary = {
        "rows": len(master),
        "raw_rows": len(df_raw) if df_raw is not None else 0,
        "master_path": str(master_path),
        "raw_path": str(raw_path),
        "status": "OK" if len(master) > 0 else "EMPTY",
    }

    logger.info("=" * 60)
    logger.info("SBA DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Raw rows:    {summary['raw_rows']:,}")
    logger.info(f"  Master rows: {summary['rows']:,}")
    logger.info(f"  Status:      {summary['status']}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download SBA Disaster Loan data for Puerto Rico"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if raw file already exists",
    )
    args = parser.parse_args()

    summary = _run(force=args.force)

    print(f"\nSBA download complete.")
    print(f"  Raw rows:    {summary['raw_rows']:,}")
    print(f"  Master rows: {summary['rows']:,}")
    print(f"  Master path: {summary['master_path']}")
    print(f"  Status:      {summary['status']}")
    return 0 if summary["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
