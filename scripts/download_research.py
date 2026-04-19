"""
Download federal research grants to Puerto Rico institutions.

Sources:
  1. NIH RePORTER  — https://api.reporter.nih.gov/v2/projects/search  (POST, paginated)
  2. NSF Awards    — https://api.nsf.gov/services/v1/awards.json       (GET, paginated)

Both sources require no authentication.

Usage:
  python3 scripts/download_research.py             # both NIH and NSF
  python3 scripts/download_research.py --nih-only
  python3 scripts/download_research.py --nsf-only
  python3 scripts/download_research.py --force
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

NIH_API_URL = "https://api.reporter.nih.gov/v2/projects/search"
NSF_API_URL = "https://api.nsf.gov/services/v1/awards.json"

NIH_PAGE_SIZE = 500
NSF_PAGE_SIZE = 25
NIH_SLEEP = 0.3
NSF_SLEEP = 0.3

# Canonical master columns (order matters for output)
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
    "pi_name",
    "source_file",
    "source_dataset",
    "award_category",
]

# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _raw_research_dir(root: Path) -> Path:
    """Return data/staging/raw/research/, creating it if needed."""
    d = root / "data" / "staging" / "raw" / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _processed_dir(root: Path) -> Path:
    """Return data/staging/processed/, creating it if needed."""
    d = root / "data" / "staging" / "processed"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _strip_date(value) -> str:
    """
    Take the date portion of an ISO datetime string or plain date.
    '2023-07-01T00:00:00Z' -> '2023-07-01'
    '2023-07-01'           -> '2023-07-01'
    Returns empty string on None / unparseable.
    """
    if not value:
        return ""
    s = str(value).strip()
    if "T" in s:
        s = s.split("T")[0]
    # Keep only YYYY-MM-DD if that's what we have
    return s[:10] if len(s) >= 10 else s


def _mmddyyyy_to_iso(value) -> str:
    """
    Convert MM/DD/YYYY -> YYYY-MM-DD.
    Returns empty string on failure.
    """
    if not value:
        return ""
    s = str(value).strip()
    try:
        parts = s.split("/")
        if len(parts) == 3:
            mm, dd, yyyy = parts
            return f"{yyyy}-{mm.zfill(2)}-{dd.zfill(2)}"
    except Exception:
        pass
    return s  # return as-is if we can't parse


def _safe_float(value, default: float = 0.0) -> float:
    """Parse a value as float; return default on failure."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# NIH RePORTER downloader
# ---------------------------------------------------------------------------

def download_nih(root: Path, force: bool, logger) -> pd.DataFrame:
    """
    Download all NIH RePORTER grants for Puerto Rico (org_state=PR, 2000-2025).
    Returns a DataFrame with canonical columns + pi_name + agency_code.
    Writes raw CSV to data/staging/raw/research/nih_raw.csv.
    """
    raw_path = _raw_research_dir(root) / "nih_raw.csv"

    if raw_path.exists() and not force:
        logger.info(f"NIH raw file already exists: {raw_path} (use --force to re-download)")
        df = pd.read_csv(raw_path, dtype=str, low_memory=False)
        logger.info(f"NIH: loaded {len(df):,} rows from cache")
        return df

    logger.info("NIH RePORTER: starting download (PR grants, 2000-2025)...")

    all_records = []
    offset = 0
    total = None
    page_num = 0

    while True:
        page_num += 1
        payload = {
            "criteria": {
                "org_states": ["PR"],
                "date_start": "2000-01-01",
                "date_end": "2025-12-31",
            },
            "include_fields": [
                "ApplId",
                "ProjectNum",
                "OrgName",
                "OrgCity",
                "OrgState",
                "ContactPiName",
                "ProjectTitle",
                "AwardAmount",
                "FiscalYear",
                "AgencyCode",
                "ProjectStartDate",
                "ProjectEndDate",
            ],
            "offset": offset,
            "limit": NIH_PAGE_SIZE,
            "sort_field": "fiscal_year",
            "sort_order": "desc",
        }

        try:
            resp = requests.post(
                NIH_API_URL,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=60,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(f"NIH HTTP error on page {page_num} (offset={offset}): {exc}")
            break
        except requests.RequestException as exc:
            logger.error(f"NIH request error on page {page_num} (offset={offset}): {exc}")
            break

        try:
            data = resp.json()
        except ValueError as exc:
            logger.error(f"NIH JSON parse error on page {page_num}: {exc}")
            break

        meta = data.get("meta", {})
        results = data.get("results", [])

        if total is None:
            total = meta.get("total", 0)
            logger.info(f"NIH: total records reported = {total:,}")

        if not results:
            logger.info(f"NIH: no results on page {page_num}, stopping.")
            break

        logger.info(
            f"NIH: page {page_num} — offset={offset}, got {len(results)} records "
            f"(cumulative={len(all_records) + len(results):,}/{total:,})"
        )

        for rec in results:
            # Flatten ContactPiName
            pi_raw = rec.get("contact_pi_name") or {}
            if isinstance(pi_raw, dict):
                first = pi_raw.get("first_name", "") or ""
                last = pi_raw.get("last_name", "") or ""
                pi_name = f"{last.strip()}, {first.strip()}".strip(", ")
            else:
                pi_name = str(pi_raw).strip()

            award_date = _strip_date(rec.get("project_start_date", ""))

            row = {
                "award_id": str(rec.get("project_num", "") or ""),
                "recipient_name": str(rec.get("org_name", "") or ""),
                "recipient_uei": "",
                "awarding_agency": "Department of Health and Human Services",
                "awarding_sub_agency": str(rec.get("agency_code", "") or ""),
                "obligated_amount": _safe_float(rec.get("award_amount")),
                "award_date": award_date,
                "fiscal_year": str(rec.get("fiscal_year", "") or ""),
                "pop_state": "PR",
                "pop_county": str(rec.get("org_city", "") or ""),
                "description": str(rec.get("project_title", "") or ""),
                "pi_name": pi_name,
                "source_file": "nih_raw.csv",
                "source_dataset": "nih",
                "award_category": "grant",
                # Extra raw columns
                "agency_code": str(rec.get("agency_code", "") or ""),
            }
            all_records.append(row)

        offset += len(results)

        # Stop if we've retrieved everything or got a partial page
        if total is not None and offset >= total:
            logger.info("NIH: reached total record count, stopping pagination.")
            break
        if len(results) < NIH_PAGE_SIZE:
            logger.info("NIH: partial page received, assuming last page.")
            break

        time.sleep(NIH_SLEEP)

    if not all_records:
        logger.warning("NIH: no records retrieved — returning empty DataFrame.")
        return pd.DataFrame(columns=MASTER_COLUMNS + ["agency_code"])

    df = pd.DataFrame(all_records)
    df.to_csv(raw_path, index=False)
    logger.info(f"NIH: saved {len(df):,} rows -> {raw_path}")
    return df


# ---------------------------------------------------------------------------
# NSF Awards downloader
# ---------------------------------------------------------------------------

def download_nsf(root: Path, force: bool, logger) -> pd.DataFrame:
    """
    Download all NSF Awards for Puerto Rico institutions (stateCode=PR, 2000-2025).
    Returns a DataFrame with canonical columns + pi_name.
    Writes raw CSV to data/staging/raw/research/nsf_raw.csv.
    """
    raw_path = _raw_research_dir(root) / "nsf_raw.csv"

    if raw_path.exists() and not force:
        logger.info(f"NSF raw file already exists: {raw_path} (use --force to re-download)")
        df = pd.read_csv(raw_path, dtype=str, low_memory=False)
        logger.info(f"NSF: loaded {len(df):,} rows from cache")
        return df

    logger.info("NSF Awards: starting download (PR institutions, 2000-2025)...")

    all_records = []
    offset = 1  # NSF uses 1-based offset
    page_num = 0

    while True:
        page_num += 1
        params = {
            "stateCode": "PR",
            "printFields": (
                "id,agency,awardeeName,awardeeCity,awardeeStateCode,"
                "title,fundsObligatedAmt,date,startDate,expDate,"
                "piFirstName,piLastName"
            ),
            "offset": offset,
            "dateStart": "01/01/2000",
            "dateEnd": "12/31/2025",
        }

        try:
            resp = requests.get(NSF_API_URL, params=params, timeout=60)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            logger.error(f"NSF HTTP error on page {page_num} (offset={offset}): {exc}")
            break
        except requests.RequestException as exc:
            logger.error(f"NSF request error on page {page_num} (offset={offset}): {exc}")
            break

        try:
            data = resp.json()
        except ValueError as exc:
            logger.error(f"NSF JSON parse error on page {page_num}: {exc}")
            break

        response_body = data.get("response", {})
        status = response_body.get("@status", "")
        if status and status != "OK":
            logger.warning(f"NSF: non-OK status '{status}' on page {page_num}, stopping.")
            break

        awards_raw = response_body.get("award")

        # awards_raw may be None, a list, or a single dict
        if awards_raw is None:
            logger.warning(
                f"NSF: 'award' key missing on page {page_num}. "
                f"Response keys: {list(response_body.keys())}  "
                f"Raw snippet: {str(data)[:400]}"
            )
            break
        if isinstance(awards_raw, dict):
            # Single result returned as dict instead of list
            awards = [awards_raw]
        else:
            awards = list(awards_raw)

        if not awards:
            logger.info(f"NSF: empty award list on page {page_num}, stopping.")
            break

        logger.info(
            f"NSF: page {page_num} — offset={offset}, got {len(awards)} records "
            f"(cumulative={len(all_records) + len(awards):,})"
        )

        for rec in awards:
            pi_first = str(rec.get("piFirstName", "") or "").strip()
            pi_last = str(rec.get("piLastName", "") or "").strip()
            pi_name = f"{pi_last}, {pi_first}".strip(", ")

            # Prefer startDate; fall back to date
            raw_date = rec.get("startDate") or rec.get("date") or ""
            award_date = _mmddyyyy_to_iso(raw_date)

            nsf_id = str(rec.get("id", "") or "").strip()
            award_id = f"NSF-{nsf_id}" if nsf_id else ""

            row = {
                "award_id": award_id,
                "recipient_name": str(rec.get("awardeeName", "") or ""),
                "recipient_uei": "",
                "awarding_agency": "National Science Foundation",
                "awarding_sub_agency": "",
                "obligated_amount": _safe_float(rec.get("fundsObligatedAmt")),
                "award_date": award_date,
                "fiscal_year": "",
                "pop_state": str(rec.get("awardeeStateCode", "") or ""),
                "pop_county": str(rec.get("awardeeCity", "") or ""),
                "description": str(rec.get("title", "") or ""),
                "pi_name": pi_name,
                "source_file": "nsf_raw.csv",
                "source_dataset": "nsf",
                "award_category": "grant",
            }
            all_records.append(row)

        offset += len(awards)

        # If we got fewer than a full page, we've reached the end
        if len(awards) < NSF_PAGE_SIZE:
            logger.info("NSF: partial page received, assuming last page.")
            break

        time.sleep(NSF_SLEEP)

    if not all_records:
        logger.warning("NSF: no records retrieved — returning empty DataFrame.")
        return pd.DataFrame(columns=MASTER_COLUMNS)

    df = pd.DataFrame(all_records)
    df.to_csv(raw_path, index=False)
    logger.info(f"NSF: saved {len(df):,} rows -> {raw_path}")
    return df


# ---------------------------------------------------------------------------
# Combine + deduplicate
# ---------------------------------------------------------------------------

def build_master(nih_df: pd.DataFrame, nsf_df: pd.DataFrame, root: Path, logger) -> pd.DataFrame:
    """
    Combine NIH and NSF DataFrames into a deduplicated master CSV.
    Writes to data/staging/processed/pr_research_master.csv.
    Returns the combined DataFrame.
    """
    frames = []
    if not nih_df.empty:
        frames.append(nih_df)
    if not nsf_df.empty:
        frames.append(nsf_df)

    if not frames:
        logger.warning("Both NIH and NSF returned empty DataFrames; master will be empty.")
        master_df = pd.DataFrame(columns=MASTER_COLUMNS)
    else:
        combined = pd.concat(frames, ignore_index=True, sort=False)

        # Ensure all master columns exist
        for col in MASTER_COLUMNS:
            if col not in combined.columns:
                combined[col] = ""

        # Keep only master columns (drop extras like agency_code)
        master_df = combined[MASTER_COLUMNS].copy()

        # Deduplicate by award_id, keeping first occurrence
        before = len(master_df)
        master_df = master_df.drop_duplicates(subset=["award_id"], keep="first")
        dupes = before - len(master_df)
        if dupes:
            logger.info(f"Master: removed {dupes:,} duplicate award_id rows.")

    out_path = _processed_dir(root) / "pr_research_master.csv"
    master_df.to_csv(out_path, index=False)
    logger.info(f"Master: saved {len(master_df):,} rows -> {out_path}")
    return master_df


# ---------------------------------------------------------------------------
# Main entry points
# ---------------------------------------------------------------------------

def run(root: Path = None) -> dict:
    """
    Main programmatic entry point.

    Parameters
    ----------
    root : Path, optional
        Project root directory. Defaults to PROJECT_ROOT from config.

    Returns
    -------
    dict with keys: nih_rows, nsf_rows, total_rows, master_path
    """
    return _run_internal(root=root, nih_only=False, nsf_only=False, force=False)


def _run_internal(
    root: Path = None,
    nih_only: bool = False,
    nsf_only: bool = False,
    force: bool = False,
) -> dict:
    if root is None:
        root = PROJECT_ROOT

    logger = setup_logging("download_research")
    logger.info("=== download_research.py started ===")
    logger.info(f"root={root}  nih_only={nih_only}  nsf_only={nsf_only}  force={force}")

    nih_df = pd.DataFrame()
    nsf_df = pd.DataFrame()

    if not nsf_only:
        nih_df = download_nih(root=root, force=force, logger=logger)

    if not nih_only:
        nsf_df = download_nsf(root=root, force=force, logger=logger)

    master_df = build_master(nih_df, nsf_df, root=root, logger=logger)

    result = {
        "nih_rows": len(nih_df),
        "nsf_rows": len(nsf_df),
        "total_rows": len(master_df),
        "master_path": str(_processed_dir(root) / "pr_research_master.csv"),
    }
    logger.info(f"=== download_research.py finished: {result} ===")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download NIH and NSF research grants to Puerto Rico institutions."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--nih-only",
        action="store_true",
        help="Download NIH RePORTER data only.",
    )
    group.add_argument(
        "--nsf-only",
        action="store_true",
        help="Download NSF Awards data only.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even if raw files already exist.",
    )
    args = parser.parse_args()

    result = _run_internal(
        root=PROJECT_ROOT,
        nih_only=args.nih_only,
        nsf_only=args.nsf_only,
        force=args.force,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
