"""
Download HUD Community Development Block Grant - Disaster Recovery (CDBG-DR) data
for Puerto Rico.

Puerto Rico received ~$21B in CDBG-DR grants, administered by PRDOH / COR3.

Multi-source approach with graceful degradation:
  Source A: USASpending prime awards (HUD grants to PR)
  Source B: COR3 transparency API (recovery.pr.gov)
  Source C: Pre-existing local files in data/staging/raw/cdbg_dr/
  Fallback:  Log instructions for manual download

Output:
  data/staging/raw/cdbg_dr/cdbg_dr_usaspending.csv     (from Source A)
  data/staging/processed/pr_cdbg_dr_master.csv          (canonical master)

Usage:
  python3 scripts/download_cdbg_dr.py            # full run
  python3 scripts/download_cdbg_dr.py --force    # re-download even if file exists
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import pandas as pd
import requests

from scripts.config import PROCESSED_DIR, PROJECT_ROOT, setup_logging

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

USASPENDING_URL = "https://api.usaspending.gov/api/v2/search/spending_by_award/"

HUD_GRANT_TYPE_CODES = ["02", "03"]  # Block Grant, Formula Grant

USASPENDING_FIELDS = [
    "Award ID",
    "Recipient Name",
    "recipient_uei",
    "Total Obligation",
    "Start Date",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Description",
]

# Time period covering post-Maria and post-Fiona disaster allocations
CDBG_DR_TIME_PERIOD = [{"start_date": "2017-10-01", "end_date": "2025-09-30"}]

COR3_API_URLS = [
    "https://recovery.pr.gov/api/projects",
    "https://recovery.pr.gov/en/api/",
]

MANUAL_DOWNLOAD_URL = "https://cdbg-dr.pr.gov/en/"
MANUAL_DOWNLOAD_MSG = (
    "CDBG-DR subgrantee data: Download from https://cdbg-dr.pr.gov/en/ "
    "— Action Plans and Quarterly Performance Reports contain contractor/subgrantee details. "
    "Save Excel files to data/staging/raw/cdbg_dr/"
)

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

PAGE_LIMIT = 100
PAGE_SLEEP = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = [2, 4, 8]


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "ContractSweeper/1.0", "Content-Type": "application/json"})
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


def _post_with_retry(
    session: requests.Session,
    url: str,
    payload: dict,
    logger,
) -> dict | None:
    """POST with retry/backoff. Returns parsed JSON or None."""
    last_err = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = session.post(url, json=payload, timeout=60)
            if resp.status_code == 429:
                logger.warning("  Rate limited (429) — sleeping 30s then retrying")
                time.sleep(30)
                resp = session.post(url, json=payload, timeout=60)
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
# Source A: USASpending prime awards
# ---------------------------------------------------------------------------

def _build_usaspending_payload(filter_type: str, page: int) -> dict:
    """
    Build the spending_by_award POST payload.
    filter_type: "pop" (place of performance) or "recipient" (recipient location).
    """
    base_filters = {
        "award_type_codes": HUD_GRANT_TYPE_CODES,
        "agencies": [
            {
                "type": "awarding",
                "tier": "toptier",
                "name": "Department of Housing and Urban Development",
            }
        ],
        "time_period": CDBG_DR_TIME_PERIOD,
    }

    if filter_type == "pop":
        base_filters["place_of_performance_locations"] = [
            {"country": "USA", "state": "PR"}
        ]
    else:
        base_filters["recipient_locations"] = [
            {"country": "USA", "state": "PR"}
        ]

    return {
        "filters": base_filters,
        "fields": USASPENDING_FIELDS,
        "page": page,
        "limit": PAGE_LIMIT,
        "subawards": False,
    }


def _paginate_usaspending(
    session: requests.Session,
    filter_type: str,
    label: str,
    logger,
) -> list[dict]:
    """
    Paginate the USASpending spending_by_award endpoint.
    Returns a flat list of award dicts.
    """
    all_records: list[dict] = []
    page = 1
    has_next = True

    while has_next:
        payload = _build_usaspending_payload(filter_type, page)
        logger.info(f"  USASpending [{label}] page {page}...")

        data = _post_with_retry(session, USASPENDING_URL, payload, logger)
        if data is None:
            logger.error(f"  USASpending [{label}] failed at page {page} — stopping")
            break

        results = data.get("results", [])
        if not results:
            break

        all_records.extend(results)
        logger.info(f"  USASpending [{label}]: {len(all_records):,} records so far")

        page_meta = data.get("page_metadata", {})
        has_next = page_meta.get("hasNext", False)
        page += 1

        if has_next:
            time.sleep(PAGE_SLEEP)

    return all_records


def _fetch_usaspending(session: requests.Session, logger) -> list[dict]:
    """
    Run both POP and recipient-location queries; deduplicate by Award ID.
    """
    logger.info("  Fetching HUD CDBG-DR grants (place of performance = PR)...")
    pop_records = _paginate_usaspending(session, "pop", "pop", logger)

    logger.info("  Fetching HUD CDBG-DR grants (recipient location = PR)...")
    rec_records = _paginate_usaspending(session, "recipient", "recipient", logger)

    # Deduplicate by Award ID
    seen: set[str] = set()
    combined: list[dict] = []
    for r in pop_records + rec_records:
        award_id = r.get("Award ID", "")
        if award_id not in seen:
            seen.add(award_id)
            combined.append(r)

    logger.info(
        f"  USASpending total: {len(pop_records):,} pop + {len(rec_records):,} recipient "
        f"→ {len(combined):,} deduplicated"
    )
    return combined


def _normalize_usaspending(records: list[dict], source_file: str) -> pd.DataFrame:
    """Map USASpending records to canonical master columns."""
    if not records:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    rows = []
    for r in records:
        award_date = r.get("Start Date", "")
        rows.append({
            "award_id": r.get("Award ID", ""),
            "recipient_name": r.get("Recipient Name", ""),
            "recipient_uei": r.get("recipient_uei", ""),
            "awarding_agency": r.get("Awarding Agency", "Department of Housing and Urban Development"),
            "awarding_sub_agency": r.get("Awarding Sub Agency", ""),
            "obligated_amount": r.get("Total Obligation", ""),
            "award_date": award_date,
            "fiscal_year": _derive_fiscal_year(award_date),
            "pop_state": "PR",
            "pop_county": "",
            "description": r.get("Description", ""),
            "source_file": source_file,
            "source_dataset": "cdbg_dr",
            "award_category": "grant",
        })

    return pd.DataFrame(rows, columns=MASTER_COLUMNS)


# ---------------------------------------------------------------------------
# Source B: COR3 transparency API
# ---------------------------------------------------------------------------

def _fetch_cor3(session: requests.Session, logger) -> list[dict]:
    """
    Try COR3 recovery API endpoints. Returns list of project dicts or empty list.
    Fails silently on any error.
    """
    for url in COR3_API_URLS:
        logger.info(f"  Trying COR3 API: {url}")
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                logger.info(f"  COR3 returned HTTP {resp.status_code} — skipping")
                continue
            content_type = resp.headers.get("Content-Type", "")
            if "json" not in content_type.lower():
                logger.info(f"  COR3 response is not JSON (Content-Type: {content_type}) — skipping")
                continue
            data = resp.json()
            # Data might be a list or a dict with a 'data'/'results' key
            if isinstance(data, list):
                logger.info(f"  COR3 returned {len(data):,} records")
                return data
            if isinstance(data, dict):
                for key in ("data", "results", "projects", "records"):
                    if key in data and isinstance(data[key], list):
                        logger.info(f"  COR3 returned {len(data[key]):,} records (key='{key}')")
                        return data[key]
            logger.info("  COR3 response format unrecognized — skipping")
        except Exception as e:
            logger.info(f"  COR3 request failed ({e}) — skipping")

    return []


def _normalize_cor3(records: list[dict], source_file: str) -> pd.DataFrame:
    """Map COR3 project records to canonical master columns."""
    if not records:
        return pd.DataFrame(columns=MASTER_COLUMNS)

    rows = []
    for i, r in enumerate(records):
        # COR3 field names vary; try multiple candidates
        recipient_name = (
            r.get("subrecipient_name") or r.get("recipient_name") or
            r.get("contractor") or r.get("applicant") or r.get("entity_name") or ""
        )
        description = (
            r.get("project_name") or r.get("project_title") or
            r.get("description") or r.get("category") or ""
        )
        obligated_amount = (
            r.get("obligated_amount") or r.get("total_obligation") or
            r.get("amount") or r.get("grant_amount") or r.get("federal_amount") or ""
        )
        award_date = (
            r.get("award_date") or r.get("start_date") or
            r.get("date") or r.get("period") or ""
        )
        award_id_raw = (
            r.get("award_id") or r.get("project_id") or r.get("id") or str(i)
        )
        award_id = f"CDBG-COR3-{award_id_raw}"

        rows.append({
            "award_id": award_id,
            "recipient_name": str(recipient_name).strip(),
            "recipient_uei": str(r.get("uei", r.get("sam_uei", ""))).strip(),
            "awarding_agency": "Department of Housing and Urban Development",
            "awarding_sub_agency": "",
            "obligated_amount": str(obligated_amount).strip(),
            "award_date": str(award_date).strip() if award_date else "",
            "fiscal_year": _derive_fiscal_year(award_date),
            "pop_state": "PR",
            "pop_county": str(r.get("municipality", r.get("county", ""))).strip(),
            "description": str(description).strip(),
            "source_file": source_file,
            "source_dataset": "cdbg_dr",
            "award_category": "grant",
        })

    return pd.DataFrame(rows, columns=MASTER_COLUMNS)


# ---------------------------------------------------------------------------
# Source C: Pre-existing local files
# ---------------------------------------------------------------------------

def _load_local_files(raw_dir: Path, logger) -> pd.DataFrame:
    """
    Scan raw_dir for any .csv or .xlsx files (other than the USASpending output)
    and attempt to parse them into the canonical schema.
    """
    frames: list[pd.DataFrame] = []
    for ext in ("*.csv", "*.xlsx"):
        for fpath in sorted(raw_dir.glob(ext)):
            if fpath.name == "cdbg_dr_usaspending.csv":
                continue  # skip the file we write ourselves
            logger.info(f"  Loading local file: {fpath.name}")
            try:
                if fpath.suffix.lower() == ".xlsx":
                    try:
                        import openpyxl  # noqa: F401
                        df = pd.read_excel(fpath, dtype=str, engine="openpyxl")
                    except ImportError:
                        logger.warning(
                            f"  openpyxl not installed — cannot read {fpath.name}. "
                            "Run: pip install openpyxl"
                        )
                        continue
                else:
                    df = pd.read_csv(fpath, dtype=str, low_memory=False, encoding="utf-8-sig")

                if df.empty:
                    logger.info(f"  {fpath.name} is empty — skipping")
                    continue

                logger.info(f"  {fpath.name}: {len(df):,} rows, columns: {list(df.columns[:8])}")
                normalized = _normalize_local_df(df, fpath.name)
                if not normalized.empty:
                    frames.append(normalized)
            except Exception as e:
                logger.warning(f"  Failed to read {fpath.name}: {e}")

    if frames:
        combined = pd.concat(frames, ignore_index=True)
        logger.info(f"  Local files total: {len(combined):,} rows")
        return combined
    return pd.DataFrame(columns=MASTER_COLUMNS)


def _normalize_local_df(df: pd.DataFrame, source_file: str) -> pd.DataFrame:
    """
    Best-effort mapping of a locally-stored CDBG-DR file to canonical columns.
    Uses fuzzy column matching.
    """
    # Normalize column names for matching
    col_lower = {c.lower().strip(): c for c in df.columns}

    def find_col(*candidates) -> pd.Series:
        for candidate in candidates:
            if candidate in df.columns:
                return df[candidate]
            if candidate.lower() in col_lower:
                return df[col_lower[candidate.lower()]]
        return pd.Series("", index=df.index)

    # Build rows
    award_id_series = find_col(
        "Award ID", "award_id", "Contract Number", "Project ID", "project_id"
    )
    recipient_series = find_col(
        "Recipient Name", "recipient_name", "Vendor Name", "Contractor",
        "Subrecipient", "Applicant", "Entity Name"
    )
    uei_series = find_col("recipient_uei", "UEI", "SAM UEI")
    agency_series = find_col(
        "Awarding Agency", "awarding_agency", "Agency"
    )
    sub_agency_series = find_col(
        "Awarding Sub Agency", "awarding_sub_agency", "Sub Agency"
    )
    amount_series = find_col(
        "Total Obligation", "obligated_amount", "Award Amount",
        "Amount Obligated", "Federal Amount", "Grant Amount"
    )
    date_series = find_col(
        "Start Date", "award_date", "Date Signed", "Approval Date"
    )
    state_series = find_col(
        "pop_state", "Place of Performance State Code",
        "State Code", "State"
    )
    county_series = find_col(
        "pop_county", "Place of Performance County Name",
        "County", "Municipality"
    )
    desc_series = find_col(
        "Description", "description", "Project Name", "Project Title"
    )

    rows = []
    for i in range(len(df)):
        award_id_val = str(award_id_series.iloc[i]).strip() if len(award_id_series) > i else ""
        if not award_id_val or award_id_val == "nan":
            award_id_val = f"CDBG-LOCAL-{i}"
        award_date_val = str(date_series.iloc[i]).strip() if len(date_series) > i else ""
        if award_date_val == "nan":
            award_date_val = ""
        state_val = str(state_series.iloc[i]).strip() if len(state_series) > i else "PR"
        if state_val in ("nan", ""):
            state_val = "PR"

        rows.append({
            "award_id": award_id_val,
            "recipient_name": str(recipient_series.iloc[i]).strip() if len(recipient_series) > i else "",
            "recipient_uei": str(uei_series.iloc[i]).strip() if len(uei_series) > i else "",
            "awarding_agency": (
                str(agency_series.iloc[i]).strip()
                if len(agency_series) > i and str(agency_series.iloc[i]).strip() not in ("nan", "")
                else "Department of Housing and Urban Development"
            ),
            "awarding_sub_agency": str(sub_agency_series.iloc[i]).strip() if len(sub_agency_series) > i else "",
            "obligated_amount": str(amount_series.iloc[i]).strip() if len(amount_series) > i else "",
            "award_date": award_date_val,
            "fiscal_year": _derive_fiscal_year(award_date_val),
            "pop_state": state_val,
            "pop_county": str(county_series.iloc[i]).strip() if len(county_series) > i else "",
            "description": str(desc_series.iloc[i]).strip() if len(desc_series) > i else "",
            "source_file": source_file,
            "source_dataset": "cdbg_dr",
            "award_category": "grant",
        })

    return pd.DataFrame(rows, columns=MASTER_COLUMNS)


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

    raw_dir = root / "data" / "staging" / "raw" / "cdbg_dr"
    raw_usa_path = raw_dir / "cdbg_dr_usaspending.csv"
    master_path = root / "data" / "staging" / "processed" / "pr_cdbg_dr_master.csv"

    raw_dir.mkdir(parents=True, exist_ok=True)
    master_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("download_cdbg_dr")
    logger.info("Starting CDBG-DR download for Puerto Rico...")

    all_frames: list[pd.DataFrame] = []

    # ------------------------------------------------------------------
    # Source A: USASpending
    # ------------------------------------------------------------------
    if not force and _file_has_data(raw_usa_path):
        logger.info(f"  USASpending raw file exists ({raw_usa_path.name}) — loading")
        try:
            df_usa_raw = pd.read_csv(raw_usa_path, dtype=str, low_memory=False)
            df_usa = _normalize_usaspending(
                df_usa_raw.to_dict("records"), raw_usa_path.name
            )
        except Exception as e:
            logger.error(f"  Failed to load existing USASpending raw file: {e}")
            df_usa = pd.DataFrame(columns=MASTER_COLUMNS)
    else:
        logger.info("  Querying USASpending for HUD CDBG-DR grants (PR)...")
        session = _session()
        usa_records = _fetch_usaspending(session, logger)
        session.close()

        if usa_records:
            df_usa_raw = pd.DataFrame(usa_records)
            df_usa_raw.to_csv(raw_usa_path, index=False, encoding="utf-8")
            logger.info(f"  USASpending raw: {len(df_usa_raw):,} rows → {raw_usa_path.name}")
            df_usa = _normalize_usaspending(usa_records, raw_usa_path.name)
        else:
            logger.warning("  USASpending returned 0 CDBG-DR records for PR")
            df_usa = pd.DataFrame(columns=MASTER_COLUMNS)
            # Write empty raw file so it exists for downstream checks
            pd.DataFrame(columns=USASPENDING_FIELDS).to_csv(raw_usa_path, index=False)

    if not df_usa.empty:
        logger.info(f"  Source A (USASpending): {len(df_usa):,} rows")
        all_frames.append(df_usa)

    # ------------------------------------------------------------------
    # Source B: COR3 API
    # ------------------------------------------------------------------
    logger.info("  Trying COR3 transparency API...")
    session_b = _session()
    cor3_records = _fetch_cor3(session_b, logger)
    session_b.close()

    if cor3_records:
        df_cor3 = _normalize_cor3(cor3_records, "cor3_api")
        logger.info(f"  Source B (COR3): {len(df_cor3):,} rows")
        all_frames.append(df_cor3)
    else:
        logger.info("  Source B (COR3 API): not available — skipping")

    # ------------------------------------------------------------------
    # Source C: Pre-existing local files
    # ------------------------------------------------------------------
    logger.info("  Checking for pre-existing local files in raw/cdbg_dr/...")
    df_local = _load_local_files(raw_dir, logger)
    if not df_local.empty:
        logger.info(f"  Source C (local files): {len(df_local):,} rows")
        all_frames.append(df_local)

    # ------------------------------------------------------------------
    # Combine all sources
    # ------------------------------------------------------------------
    if all_frames:
        master = pd.concat(all_frames, ignore_index=True)
        # Deduplicate by award_id (keep first occurrence)
        before_dedup = len(master)
        master = master.drop_duplicates(subset=["award_id"], keep="first")
        logger.info(
            f"  Combined: {before_dedup:,} rows → {len(master):,} after deduplication"
        )
    else:
        logger.warning(MANUAL_DOWNLOAD_MSG)
        master = pd.DataFrame(columns=MASTER_COLUMNS)

    # ------------------------------------------------------------------
    # Write master (always — even if empty — so downstream doesn't fail)
    # ------------------------------------------------------------------
    master.to_csv(master_path, index=False, encoding="utf-8")
    logger.info(f"  Master written: {len(master):,} rows → {master_path.name}")

    status = "OK" if len(master) > 0 else "MANUAL_DOWNLOAD_REQUIRED"

    summary: dict = {
        "rows": len(master),
        "master_path": str(master_path),
        "raw_usaspending_path": str(raw_usa_path),
        "status": status,
    }
    if status == "MANUAL_DOWNLOAD_REQUIRED":
        summary["instructions"] = MANUAL_DOWNLOAD_MSG

    logger.info("=" * 60)
    logger.info("CDBG-DR DOWNLOAD SUMMARY")
    logger.info("=" * 60)
    logger.info(f"  Master rows: {summary['rows']:,}")
    logger.info(f"  Status:      {summary['status']}")

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download HUD CDBG-DR data for Puerto Rico"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if raw file already exists",
    )
    args = parser.parse_args()

    summary = _run(force=args.force)

    print("\nCDBG-DR download complete.")
    print(f"  Master rows: {summary['rows']:,}")
    print(f"  Master path: {summary['master_path']}")
    print(f"  Status:      {summary['status']}")
    if "instructions" in summary:
        print(f"\n  NOTE: {summary['instructions']}")
    return 0 if summary["status"] == "OK" else 1


if __name__ == "__main__":
    sys.exit(main())
