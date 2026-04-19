"""
Download OpenFEMA datasets for Puerto Rico:
  1. Public Assistance Funded Projects Details (post-disaster grants)
  2. Hazard Mitigation Grant Program (resilience grants)

Usage:
  python3 scripts/download_fema.py             # downloads both PA and HMGP
  python3 scripts/download_fema.py --pa-only   # only Public Assistance
  python3 scripts/download_fema.py --hmgp-only # only Hazard Mitigation
  python3 scripts/download_fema.py --force     # re-download even if file exists
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, PROCESSED_DIR, setup_logging

import requests
import pandas as pd
import time
import argparse
import json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEMA_BASE = "https://www.fema.gov/api/open/v2/"

PA_ENDPOINT = FEMA_BASE + "PublicAssistanceFundedProjectsDetails"
PA_DATA_KEY = "PublicAssistanceFundedProjectsDetails"

HMGP_ENDPOINT = FEMA_BASE + "HazardMitigationGrantProgramDisasterSummaries"
HMGP_DATA_KEY = "HazardMitigationGrantProgramDisasterSummaries"

HMA_ENDPOINT = FEMA_BASE + "HmaSubapplications"
HMA_DATA_KEY = "HmaSubapplications"

PAGE_SIZE = 1000
SLEEP_BETWEEN_PAGES = 0.5
RETRY_SLEEP = 30

# Output directories (raw sits under data/staging/raw/)
STAGING_RAW_DIR = PROJECT_ROOT / "data" / "staging" / "raw"
PA_RAW_DIR = STAGING_RAW_DIR / "fema_pa"
HMGP_RAW_DIR = STAGING_RAW_DIR / "fema_hmgp"

PA_RAW_PATH = PA_RAW_DIR / "fema_pa_raw.csv"
HMGP_RAW_PATH = HMGP_RAW_DIR / "fema_hmgp_raw.csv"

PA_MASTER_PATH = PROCESSED_DIR / "pr_fema_pa_master.csv"
HMGP_MASTER_PATH = PROCESSED_DIR / "pr_fema_hmgp_master.csv"

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
# Helpers
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, params: dict, logger) -> dict | None:
    """
    GET the given URL with params, retry once on 429/503.
    Returns parsed JSON dict or None on failure.
    """
    for attempt in (1, 2):
        try:
            resp = requests.get(url, params=params, timeout=60)
            if resp.status_code in (429, 503):
                logger.warning(
                    "HTTP %s from %s (attempt %d), sleeping %ds then retrying...",
                    resp.status_code, url, attempt, RETRY_SLEEP,
                )
                if attempt == 1:
                    time.sleep(RETRY_SLEEP)
                    continue
                else:
                    logger.error("Retry failed with HTTP %s, skipping page.", resp.status_code)
                    return None
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            logger.error("Request error on attempt %d: %s", attempt, exc)
            if attempt == 1:
                time.sleep(RETRY_SLEEP)
            else:
                return None
    return None


def _paginate(endpoint: str, data_key: str, params: dict, logger) -> list[dict]:
    """
    Paginate through an OpenFEMA endpoint using $top/$skip.
    Returns a flat list of all record dicts.
    """
    records = []
    skip = 0
    total = None

    while True:
        page_params = dict(params)
        page_params["$top"] = PAGE_SIZE
        page_params["$skip"] = skip

        logger.info("  Fetching %s (skip=%d, top=%d)...", endpoint.split("/")[-1], skip, PAGE_SIZE)

        data = _get_with_retry(endpoint, page_params, logger)
        if data is None:
            logger.warning("  Got no data at skip=%d; stopping pagination.", skip)
            break

        # Determine total from metadata
        if total is None:
            meta = data.get("metadata", {})
            total = meta.get("count", None)
            if total is not None:
                logger.info("  Total records reported by API: %d", total)

        page_records = data.get(data_key, [])
        if not page_records:
            logger.info("  Empty page at skip=%d; stopping.", skip)
            break

        records.extend(page_records)
        logger.info("  Retrieved %d records so far.", len(records))

        skip += PAGE_SIZE

        # Stop if we've collected all records
        if total is not None and skip >= total:
            break

        time.sleep(SLEEP_BETWEEN_PAGES)

    return records


def _derive_fiscal_year(date_str) -> int | None:
    """
    Derive US Federal fiscal year from an ISO date string.
    FY starts October 1; e.g. 2017-10-01 → FY2018.
    Returns None if date_str is missing or unparseable.
    """
    if not date_str or pd.isna(date_str):
        return None
    try:
        dt = pd.to_datetime(str(date_str), errors="coerce")
        if pd.isna(dt):
            return None
        return dt.year + 1 if dt.month >= 10 else dt.year
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public Assistance Funded Projects
# ---------------------------------------------------------------------------

def _fetch_pa_records(logger) -> list[dict]:
    """Fetch all PA records for Puerto Rico from the OpenFEMA API."""
    params = {
        "$filter": "state eq 'Puerto Rico'",
        "$orderby": "projectAmount desc",
    }
    return _paginate(PA_ENDPOINT, PA_DATA_KEY, params, logger)


def _normalize_pa(records: list[dict], source_file: str) -> pd.DataFrame:
    """
    Map raw PA records to the canonical master schema.
    """
    rows = []
    for r in records:
        project_amount = r.get("projectAmount") or 0
        federal_share = r.get("federalShareObligated") or 0
        amount = federal_share if (not project_amount or project_amount == 0) else project_amount

        raw_date = r.get("projectWorksheetDate", "")
        # Strip trailing time component for cleanliness
        award_date = raw_date.split("T")[0] if raw_date else ""

        description = r.get("applicationTitle") or r.get("damageCategory") or ""

        disaster_num = str(r.get("disasterNumber", "")).strip()
        award_id = f"FEMA-PA-{disaster_num}" if disaster_num else "FEMA-PA-UNKNOWN"

        state_raw = r.get("state", "")
        pop_state = "PR" if "puerto rico" in str(state_raw).lower() else state_raw

        rows.append({
            "award_id": award_id,
            "recipient_name": r.get("applicantName", ""),
            "recipient_uei": "",
            "awarding_agency": "Federal Emergency Management Agency",
            "awarding_sub_agency": "",
            "obligated_amount": amount,
            "award_date": award_date,
            "fiscal_year": _derive_fiscal_year(award_date),
            "pop_state": pop_state,
            "pop_county": r.get("county", ""),
            "description": description,
            "source_file": source_file,
            "source_dataset": "fema_pa",
            "award_category": "disaster_assistance",
        })

    df = pd.DataFrame(rows, columns=MASTER_COLUMNS)
    return df


def download_pa(force: bool, logger) -> tuple[int, str]:
    """
    Download and save PA data.
    Returns (row_count, master_path_str).
    """
    if PA_MASTER_PATH.exists() and not force:
        logger.info("PA master already exists at %s — skipping (use --force to re-download).", PA_MASTER_PATH)
        existing = pd.read_csv(PA_MASTER_PATH, dtype=str)
        return len(existing), str(PA_MASTER_PATH)

    logger.info("=== Downloading Public Assistance Funded Projects (Puerto Rico) ===")
    PA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    records = _fetch_pa_records(logger)
    logger.info("Total PA records fetched: %d", len(records))

    if not records:
        logger.warning("No PA records returned; writing empty files.")

    # Save raw
    raw_df = pd.DataFrame(records)
    raw_df.to_csv(PA_RAW_PATH, index=False)
    logger.info("Raw PA data written to %s (%d rows).", PA_RAW_PATH, len(raw_df))

    # Normalize → master
    master_df = _normalize_pa(records, str(PA_RAW_PATH))
    master_df.to_csv(PA_MASTER_PATH, index=False)
    logger.info("PA master written to %s (%d rows).", PA_MASTER_PATH, len(master_df))

    return len(master_df), str(PA_MASTER_PATH)


# ---------------------------------------------------------------------------
# Hazard Mitigation Grant Program
# ---------------------------------------------------------------------------

def _fetch_hmgp_records(logger) -> tuple[list[dict], str]:
    """
    Try HMGP Disaster Summaries first; if empty fall back to HmaSubapplications.
    Returns (records, dataset_label).
    """
    # --- Attempt 1: HazardMitigationGrantProgramDisasterSummaries ---
    logger.info("Trying HazardMitigationGrantProgramDisasterSummaries endpoint...")
    params = {
        "$filter": "stateName eq 'Puerto Rico'",
    }
    records = _paginate(HMGP_ENDPOINT, HMGP_DATA_KEY, params, logger)

    if records:
        logger.info("HMGP disaster summaries returned %d records.", len(records))
        return records, "hmgp_summaries"

    logger.info("HMGP disaster summaries empty; trying 'PR' filter variant...")
    params_pr = {"$filter": "stateName eq 'PR'"}
    records = _paginate(HMGP_ENDPOINT, HMGP_DATA_KEY, params_pr, logger)
    if records:
        logger.info("HMGP disaster summaries (PR) returned %d records.", len(records))
        return records, "hmgp_summaries"

    # --- Attempt 2: HmaSubapplications ---
    logger.info("Falling back to HmaSubapplications endpoint...")
    hma_params = {"$filter": "stateName eq 'Puerto Rico'"}
    records = _paginate(HMA_ENDPOINT, HMA_DATA_KEY, hma_params, logger)
    if records:
        logger.info("HmaSubapplications returned %d records.", len(records))
        return records, "hma_subapplications"

    logger.info("Trying HmaSubapplications with 'PR'...")
    hma_params_pr = {"$filter": "stateName eq 'PR'"}
    records = _paginate(HMA_ENDPOINT, HMA_DATA_KEY, hma_params_pr, logger)
    if records:
        logger.info("HmaSubapplications (PR) returned %d records.", len(records))
        return records, "hma_subapplications"

    logger.warning("All HMGP/HMA endpoints returned no records.")
    return [], "none"


def _normalize_hmgp(records: list[dict], dataset_label: str, source_file: str) -> pd.DataFrame:
    """
    Map raw HMGP/HMA records to the canonical master schema.
    Handles both HazardMitigationGrantProgramDisasterSummaries and HmaSubapplications.
    """
    rows = []
    is_hma = dataset_label == "hma_subapplications"

    for r in records:
        if is_hma:
            recipient_name = r.get("subapplicantName", "")
            description = r.get("projectTitle", "")
            amount = r.get("projectAmount") or r.get("grantAmount") or 0
            disaster_num = str(r.get("disasterNumber", "")).strip()
            county = r.get("county", "")
            award_id_suffix = f"FEMA-HMGP-HMA-{disaster_num}" if disaster_num else "FEMA-HMGP-HMA"
        else:
            # HazardMitigationGrantProgramDisasterSummaries fields
            recipient_name = (
                r.get("applicantName")
                or r.get("subrecipientName")
                or r.get("programTitle")
                or ""
            )
            description = (
                r.get("projectTitle")
                or r.get("programTitle")
                or r.get("projectDescription")
                or ""
            )
            amount = (
                r.get("projectAmount")
                or r.get("grantAmount")
                or r.get("federalShareObligated")
                or r.get("totalObligated")
                or 0
            )
            disaster_num = str(r.get("disasterNumber", "")).strip()
            county = r.get("county") or r.get("subrecipientCounty") or ""
            award_id_suffix = f"FEMA-HMGP-{disaster_num}" if disaster_num else "FEMA-HMGP"

        raw_date = (
            r.get("projectWorksheetDate")
            or r.get("approvalDate")
            or r.get("applicationDate")
            or r.get("obligationDate")
            or ""
        )
        award_date = raw_date.split("T")[0] if raw_date else ""

        # award_id: include subapplication or project number if available
        sub_num = r.get("subapplicationId") or r.get("projectNumber") or ""
        award_id = f"{award_id_suffix}-{sub_num}" if sub_num else award_id_suffix

        state_raw = r.get("stateName") or r.get("state") or ""
        pop_state = "PR" if "puerto rico" in str(state_raw).lower() or str(state_raw).upper() == "PR" else state_raw

        rows.append({
            "award_id": award_id,
            "recipient_name": recipient_name,
            "recipient_uei": "",
            "awarding_agency": "Federal Emergency Management Agency",
            "awarding_sub_agency": "",
            "obligated_amount": amount,
            "award_date": award_date,
            "fiscal_year": _derive_fiscal_year(award_date),
            "pop_state": pop_state,
            "pop_county": county,
            "description": description,
            "source_file": source_file,
            "source_dataset": "fema_hmgp",
            "award_category": "grant",
        })

    df = pd.DataFrame(rows, columns=MASTER_COLUMNS)
    return df


def download_hmgp(force: bool, logger) -> tuple[int, str]:
    """
    Download and save HMGP data.
    Returns (row_count, master_path_str).
    """
    if HMGP_MASTER_PATH.exists() and not force:
        logger.info(
            "HMGP master already exists at %s — skipping (use --force to re-download).",
            HMGP_MASTER_PATH,
        )
        existing = pd.read_csv(HMGP_MASTER_PATH, dtype=str)
        return len(existing), str(HMGP_MASTER_PATH)

    logger.info("=== Downloading Hazard Mitigation Grant Program (Puerto Rico) ===")
    HMGP_RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    records, dataset_label = _fetch_hmgp_records(logger)
    logger.info("Total HMGP records fetched: %d (source: %s)", len(records), dataset_label)

    # Save raw
    raw_df = pd.DataFrame(records)
    raw_df.to_csv(HMGP_RAW_PATH, index=False)
    logger.info("Raw HMGP data written to %s (%d rows).", HMGP_RAW_PATH, len(raw_df))

    # Normalize → master
    master_df = _normalize_hmgp(records, dataset_label, str(HMGP_RAW_PATH))
    master_df.to_csv(HMGP_MASTER_PATH, index=False)
    logger.info("HMGP master written to %s (%d rows).", HMGP_MASTER_PATH, len(master_df))

    return len(master_df), str(HMGP_MASTER_PATH)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(root: Path = None) -> dict:
    """
    Download FEMA PA and HMGP datasets for Puerto Rico.

    Parameters
    ----------
    root : Path, optional
        Unused; reserved for pipeline orchestration compatibility.

    Returns
    -------
    dict with keys: pa_rows, hmgp_rows, pa_path, hmgp_path
    """
    logger = setup_logging("download_fema")

    pa_rows, pa_path = download_pa(force=False, logger=logger)
    hmgp_rows, hmgp_path = download_hmgp(force=False, logger=logger)

    result = {
        "pa_rows": pa_rows,
        "hmgp_rows": hmgp_rows,
        "pa_path": pa_path,
        "hmgp_path": hmgp_path,
    }
    logger.info("run() complete: %s", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download OpenFEMA datasets for Puerto Rico (PA and/or HMGP)."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--pa-only",
        action="store_true",
        help="Download only the Public Assistance Funded Projects dataset.",
    )
    group.add_argument(
        "--hmgp-only",
        action="store_true",
        help="Download only the Hazard Mitigation Grant Program dataset.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and overwrite existing files.",
    )
    args = parser.parse_args()

    logger = setup_logging("download_fema")

    pa_rows, hmgp_rows = 0, 0
    pa_path, hmgp_path = "", ""

    if not args.hmgp_only:
        pa_rows, pa_path = download_pa(force=args.force, logger=logger)
        logger.info("PA complete: %d rows → %s", pa_rows, pa_path)

    if not args.pa_only:
        hmgp_rows, hmgp_path = download_hmgp(force=args.force, logger=logger)
        logger.info("HMGP complete: %d rows → %s", hmgp_rows, hmgp_path)

    logger.info(
        "All done. PA rows: %d, HMGP rows: %d", pa_rows, hmgp_rows
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
