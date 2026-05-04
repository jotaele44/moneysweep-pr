"""
Download OpenFEMA PA v2 projects for Puerto Rico and save full schema to parquet.

Endpoints used:
  - PublicAssistanceFundedProjectsDetails (v2) — batched by disaster number
  - PublicAssistanceApplicants — direct state filter for PR
  - DisasterDeclarationsSummaries — to get PR disaster numbers

Usage:
  python3 scripts/download_openfema_pa_projects.py
  python3 scripts/download_openfema_pa_projects.py --force
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.parquet_utils import pq_read, pq_write
from scripts.config import PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

import requests
import urllib.parse
import pandas as pd
import time
import argparse
from datetime import date

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FEMA_BASE_V2 = "https://www.fema.gov/api/open/v2/"
FEMA_BASE_V1 = "https://www.fema.gov/api/open/v1/"

PA_V2_ENDPOINT = FEMA_BASE_V2 + "PublicAssistanceFundedProjectsDetails"
PA_V2_DATA_KEY = "PublicAssistanceFundedProjectsDetails"

PA_APPLICANTS_ENDPOINT = FEMA_BASE_V2 + "PublicAssistanceApplicants"
PA_APPLICANTS_DATA_KEY = "PublicAssistanceApplicants"

DISASTER_SUMMARIES_ENDPOINT = FEMA_BASE_V2 + "DisasterDeclarationsSummaries"
DISASTER_SUMMARIES_DATA_KEY = "DisasterDeclarationsSummaries"

PA_DISASTER_BATCH = 15
PAGE_SIZE = 1000
SLEEP_BETWEEN_PAGES = 0.5
RETRY_SLEEP = 30

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
OUTPUT_PATH = NORMALIZED_DIR / "fema_pa_projects_v2.parquet"

PA_V2_COLUMNS = [
    "disaster_number", "pw_number", "applicant_id", "applicant_name", "applicant_normalized",
    "county", "county_fips", "state_code",
    "category", "application_title", "damage_category",
    "project_amount", "federal_share_obligated", "total_obligated",
    "obligation_date", "pw_date", "closed_date",
    "latitude", "longitude",
    "source_system", "pull_date",
]

# ---------------------------------------------------------------------------
# Helpers (replicated from download_fema.py to be self-contained)
# ---------------------------------------------------------------------------

def _get_with_retry(url: str, logger) -> dict | None:
    """GET a pre-built URL with one retry on 429/503."""
    for attempt in (1, 2):
        try:
            resp = requests.get(url, timeout=60)
            if resp.status_code in (429, 503):
                logger.warning(
                    "HTTP %s from %s (attempt %d), sleeping %ds then retrying...",
                    resp.status_code, url, attempt, RETRY_SLEEP,
                )
                if attempt == 1:
                    time.sleep(RETRY_SLEEP)
                    continue
                else:
                    logger.error("Retry failed with HTTP %s, skipping.", resp.status_code)
                    return None
            if resp.status_code == 400:
                logger.error("HTTP 400 — body: %s", resp.text[:800])
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


def _paginate(endpoint: str, data_key: str, params: dict, logger,
              simple_params: dict | None = None) -> list[dict]:
    """
    Paginate an OpenFEMA endpoint using $top/$skip.
    Builds raw URL strings to avoid OData $ percent-encoding issues.
    """
    records = []
    skip = 0
    total = None

    while True:
        raw_url = f"{endpoint}?$top={PAGE_SIZE}&$skip={skip}"
        filter_clause = params.get("$filter", "")
        orderby_clause = params.get("$orderby", "")
        if filter_clause:
            raw_url += f"&$filter={filter_clause}"
        if orderby_clause:
            raw_url += f"&$orderby={orderby_clause}"
        if simple_params:
            for k, v in simple_params.items():
                raw_url += (
                    f"&{urllib.parse.quote(str(k), safe='')}="
                    f"{urllib.parse.quote(str(v), safe='')}"
                )

        logger.info("  Fetching %s (skip=%d, top=%d)...", endpoint.split("/")[-1], skip, PAGE_SIZE)
        data = _get_with_retry(raw_url, logger)
        if data is None:
            logger.warning("  No data at skip=%d; stopping pagination.", skip)
            break

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

        if total is not None and total > 0 and skip >= total:
            break

        time.sleep(SLEEP_BETWEEN_PAGES)

    return records


def _get_pr_disaster_numbers(logger) -> list[int]:
    """Fetch all FEMA disaster numbers for Puerto Rico."""
    logger.info("Fetching PR disaster numbers from DisasterDeclarationsSummaries...")
    records = _paginate(
        DISASTER_SUMMARIES_ENDPOINT,
        DISASTER_SUMMARIES_DATA_KEY,
        {"$filter": "state eq 'PR'"},
        logger,
    )
    nums = sorted({int(r["disasterNumber"]) for r in records if r.get("disasterNumber")})
    logger.info("Found %d unique PR disaster numbers.", len(nums))
    return nums


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def _map_record(r: dict, source_system: str, pull_date: str) -> dict:
    """Map a raw API record to the canonical PA v2 schema."""
    applicant_name = r.get("applicantName", "") or ""
    return {
        "disaster_number":        str(r.get("disasterNumber", "") or ""),
        "pw_number":              str(r.get("pwNumber", "") or ""),
        "applicant_id":           str(r.get("applicantId", "") or ""),
        "applicant_name":         applicant_name,
        "applicant_normalized":   _normalize_name(applicant_name),
        "county":                 str(r.get("county", r.get("countyName", "")) or ""),
        "county_fips":            str(r.get("countyFips", "") or ""),
        "state_code":             str(r.get("stateNumberCode", r.get("state", "")) or ""),
        "category":               str(r.get("category", r.get("damageCategory", "")) or ""),
        "application_title":      str(r.get("applicationTitle", "") or ""),
        "damage_category":        str(r.get("damageCategory", "") or ""),
        "project_amount":         r.get("projectAmount"),
        "federal_share_obligated": r.get("federalShareObligated"),
        "total_obligated":        r.get("totalObligated"),
        "obligation_date":        str(r.get("obligatedDate", "") or ""),
        "pw_date":                str(r.get("projectWorksheetDate", "") or ""),
        "closed_date":            str(r.get("closedProjectWorksheetDate", "") or ""),
        "latitude":               r.get("latitude"),
        "longitude":              r.get("longitude"),
        "source_system":          source_system,
        "pull_date":              pull_date,
    }


# ---------------------------------------------------------------------------
# Fetch logic
# ---------------------------------------------------------------------------

def _fetch_pa_v2_records(logger) -> list[dict]:
    """Fetch PA v2 records for PR by batching disaster numbers."""
    disaster_numbers = _get_pr_disaster_numbers(logger)
    if not disaster_numbers:
        logger.warning("No PR disaster numbers found; PA v2 fetch will be empty.")
        return []

    all_records: list[dict] = []
    batches = [
        disaster_numbers[i : i + PA_DISASTER_BATCH]
        for i in range(0, len(disaster_numbers), PA_DISASTER_BATCH)
    ]
    logger.info(
        "Fetching PA v2 records in %d batch(es) of up to %d disaster numbers each.",
        len(batches), PA_DISASTER_BATCH,
    )

    for idx, batch in enumerate(batches, start=1):
        or_filter = " or ".join(f"disasterNumber eq {n}" for n in batch)
        logger.info("Batch %d/%d: disaster numbers %s...", idx, len(batches), batch[:3])
        try:
            records = _paginate(
                PA_V2_ENDPOINT,
                PA_V2_DATA_KEY,
                {"$filter": or_filter},
                logger,
            )
            all_records.extend(records)
            logger.info("Batch %d: got %d records (total so far: %d).", idx, len(records), len(all_records))
        except Exception as exc:
            logger.error("Batch %d failed: %s", idx, exc)

    return all_records


def _fetch_pa_applicants(logger) -> list[dict]:
    """Fetch PA applicants for PR directly."""
    logger.info("Fetching PA applicants for PR...")
    try:
        records = _paginate(
            PA_APPLICANTS_ENDPOINT,
            PA_APPLICANTS_DATA_KEY,
            {"$filter": "state eq 'PR'"},
            logger,
        )
        logger.info("Fetched %d PA applicant records.", len(records))
        return records
    except Exception as exc:
        logger.error("PA applicants fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Public run() interface
# ---------------------------------------------------------------------------

def run(root=None, force=False) -> dict:
    logger = setup_logging("download_openfema_pa_projects")
    effective_root = Path(root) if root else PROJECT_ROOT
    out_path = effective_root / "data" / "normalized" / "fema_pa_projects_v2.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force:
        logger.info("Output already exists and --force not set: %s", out_path)
        try:
            existing = pq_read(out_path)
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}
        except Exception as exc:
            logger.warning("Could not read cached file (%s); re-downloading.", exc)

    pull_date = date.today().isoformat()
    logger.info("Starting OpenFEMA PA v2 download. pull_date=%s", pull_date)

    try:
        raw_records = _fetch_pa_v2_records(logger)
    except Exception as exc:
        logger.error("PA v2 fetch failed entirely: %s", exc)
        raw_records = []

    # Also fetch applicant records and merge in any applicant_id / applicant_name enrichment
    try:
        applicant_records = _fetch_pa_applicants(logger)
    except Exception as exc:
        logger.warning("PA applicants fetch failed: %s", exc)
        applicant_records = []

    if not raw_records:
        logger.warning(
            "Zero PA v2 records retrieved. Writing empty parquet.\n"
            "Manual download instructions:\n"
            "  Visit https://www.fema.gov/openfema-data-page/public-assistance-funded-projects-details-v2\n"
            "  Download CSV and place in data/raw/fema_pa/"
        )
        empty_df = pd.DataFrame(columns=PA_V2_COLUMNS)
        pq_write(empty_df, out_path)
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    # Build applicant enrichment lookup: applicantId → applicant_name
    applicant_lookup: dict[str, str] = {}
    for ar in applicant_records:
        aid = str(ar.get("applicantId", "") or "")
        aname = str(ar.get("applicantName", ar.get("subRecipientName", "")) or "")
        if aid and aname:
            applicant_lookup[aid] = aname

    # Map records to canonical schema
    mapped = []
    for r in raw_records:
        row = _map_record(r, "openfema_v2", pull_date)
        # Enrich applicant_name from applicant lookup if missing
        if not row["applicant_name"] and row["applicant_id"] in applicant_lookup:
            row["applicant_name"] = applicant_lookup[row["applicant_id"]]
            row["applicant_normalized"] = _normalize_name(row["applicant_name"])
        mapped.append(row)

    df = pd.DataFrame(mapped, columns=PA_V2_COLUMNS)
    pq_write(df, out_path)
    logger.info("Saved %d PA v2 records to %s", len(df), out_path)
    return {"rows": len(df), "path": str(out_path), "status": "OK"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Download OpenFEMA PA v2 projects for Puerto Rico.")
    parser.add_argument("--force", action="store_true", help="Re-download even if output file exists.")
    args = parser.parse_args()

    result = run(force=args.force)
    logger = setup_logging("download_openfema_pa_projects")
    logger.info("Result: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
