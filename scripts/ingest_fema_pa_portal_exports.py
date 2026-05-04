"""
Ingest authorized FEMA PA portal export files (178-PW data) from local directories,
normalize to canonical schema, and output parquet.

These are manual exports from the authorized FEMA PA portal (NOT public).
Search directories: data/raw/FEMA/ and data/raw/fema_pa/

Usage:
  python3 scripts/ingest_fema_pa_portal_exports.py
  python3 scripts/ingest_fema_pa_portal_exports.py --force
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging
from scripts.build_unified_master import _normalize_name

import pandas as pd
import argparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SEARCH_DIRS = [
    PROJECT_ROOT / "data" / "raw" / "FEMA",
    PROJECT_ROOT / "data" / "raw" / "fema_pa",
]

NORMALIZED_DIR = PROJECT_ROOT / "data" / "normalized"
OUTPUT_PATH = NORMALIZED_DIR / "fema_pa_portal_178_pws.parquet"

PORTAL_COLUMNS = [
    "pw_number", "disaster_number", "applicant_name", "applicant_normalized",
    "pw_type", "site_name", "county", "municipality",
    "eligible_amount", "federal_share", "state_share", "local_share",
    "project_description", "category", "status",
    "last_updated", "source_file",
]

# Flexible column mapping: canonical field → list of candidate column names (case-insensitive)
COLUMN_CANDIDATES: dict[str, list[str]] = {
    "pw_number": [
        "PW Number", "Project Worksheet Number", "Project Number", "PWNumber", "pw_number",
        "ProjectWorksheetNumber", "PW#", "PW Num",
    ],
    "disaster_number": [
        "Disaster Number", "Disaster", "disaster_number", "DisasterNumber",
        "FEMA Disaster Number", "Disaster No",
    ],
    "applicant_name": [
        "Applicant Name", "Applicant", "Entity Name", "applicant_name",
        "Sub-Recipient Name", "SubRecipient", "Recipient Name",
    ],
    "pw_type": [
        "PW Type", "Project Type", "Type", "pw_type",
    ],
    "site_name": [
        "Site Name", "Project Site", "Site", "site_name", "Location Name",
    ],
    "county": [
        "County", "County Name", "county", "CountyName",
    ],
    "municipality": [
        "Municipality", "City", "community", "municipality", "Town", "Municipio",
    ],
    "eligible_amount": [
        "Eligible Amount", "Project Amount", "Total Eligible", "eligible_amount",
        "projectAmount", "Total Project Amount", "Eligible Cost",
    ],
    "federal_share": [
        "Federal Share", "Federal Share Obligated", "federal_share_obligated",
        "Federal Amount", "Fed Share",
    ],
    "state_share": [
        "State Share", "State Amount", "state_share", "Non-Federal State",
    ],
    "local_share": [
        "Local Share", "Local Amount", "local_share", "Non-Federal Local", "Applicant Share",
    ],
    "project_description": [
        "Project Description", "Description", "Scope of Work", "project_description",
        "SOW", "Work Description",
    ],
    "category": [
        "Category", "Work Category", "Damage Category", "category",
        "Work Cat", "Cat",
    ],
    "status": [
        "Status", "Project Status", "Current Status", "status",
        "PW Status", "Award Status",
    ],
    "last_updated": [
        "Last Updated", "Last Modified", "Update Date", "last_updated",
        "Modified Date", "Date Updated",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_column(df_columns: list[str], candidates: list[str]) -> str | None:
    """Case-insensitive search for the first matching candidate in df_columns."""
    lower_map = {c.lower().strip(): c for c in df_columns}
    for cand in candidates:
        key = cand.lower().strip()
        if key in lower_map:
            return lower_map[key]
    return None


def _read_file(filepath: Path, logger) -> pd.DataFrame | None:
    """Try reading a file as Excel, then fall back to CSV."""
    suffix = filepath.suffix.lower()
    try:
        if suffix in (".xlsx", ".xls"):
            logger.info("  Reading Excel file: %s", filepath.name)
            return pd.read_excel(filepath, dtype=str)
        elif suffix == ".csv":
            logger.info("  Reading CSV file: %s", filepath.name)
            for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
                try:
                    return pd.read_csv(filepath, dtype=str, encoding=enc, low_memory=False)
                except UnicodeDecodeError:
                    continue
            logger.error("  Could not decode %s with any supported encoding.", filepath.name)
            return None
        else:
            # Unknown extension — try Excel first, then CSV
            logger.info("  Unknown extension %s, trying Excel then CSV: %s", suffix, filepath.name)
            try:
                return pd.read_excel(filepath, dtype=str)
            except Exception:
                try:
                    return pd.read_csv(filepath, dtype=str, encoding="utf-8-sig", low_memory=False)
                except Exception as exc2:
                    logger.error("  Could not read %s: %s", filepath.name, exc2)
                    return None
    except Exception as exc:
        logger.error("  Failed to read %s: %s", filepath.name, exc)
        return None


def _looks_like_pw_file(filepath: Path) -> bool:
    """
    Heuristic: does this file look like a PW export?
    Checks filename for keywords suggesting it contains PW data.
    """
    name_lower = filepath.name.lower()
    pw_keywords = ["pw", "project_worksheet", "project worksheet", "178", "public_assist",
                   "publicassist", "fema_pa", "pa_", "_pa_", "fema-pa"]
    return any(kw in name_lower for kw in pw_keywords)


def _normalize_df(raw_df: pd.DataFrame, source_file: str, logger) -> pd.DataFrame:
    """Map a raw DataFrame to the canonical portal schema."""
    cols = list(raw_df.columns)
    row_dicts = []

    for _, row in raw_df.iterrows():
        rec: dict = {"source_file": source_file}
        for field, candidates in COLUMN_CANDIDATES.items():
            col = _find_column(cols, candidates)
            if col is not None:
                rec[field] = str(row.get(col, "") or "").strip()
            else:
                rec[field] = ""

        # Compute normalized applicant name
        rec["applicant_normalized"] = _normalize_name(rec.get("applicant_name", ""))
        row_dicts.append(rec)

    if not row_dicts:
        return pd.DataFrame(columns=PORTAL_COLUMNS)

    out = pd.DataFrame(row_dicts, columns=PORTAL_COLUMNS)
    logger.info("  Mapped %d rows from %s.", len(out), source_file)
    return out


# ---------------------------------------------------------------------------
# Public run() interface
# ---------------------------------------------------------------------------

def run(root=None, force=False) -> dict:
    logger = setup_logging("ingest_fema_pa_portal_exports")
    effective_root = Path(root) if root else PROJECT_ROOT
    out_path = effective_root / "data" / "normalized" / "fema_pa_portal_178_pws.parquet"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if out_path.exists() and not force:
        logger.info("Output already exists and --force not set: %s", out_path)
        try:
            existing = pd.read_parquet(out_path, engine="pyarrow")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}
        except Exception as exc:
            logger.warning("Could not read cached file (%s); re-ingesting.", exc)

    # Discover search directories (adjusted for effective_root)
    search_dirs = [
        effective_root / "data" / "raw" / "FEMA",
        effective_root / "data" / "raw" / "fema_pa",
    ]

    # Discover candidate files
    candidate_files: list[Path] = []
    for search_dir in search_dirs:
        if not search_dir.exists():
            logger.info("Search directory does not exist, skipping: %s", search_dir)
            continue
        for pattern in ("*.xlsx", "*.xls", "*.csv"):
            found = list(search_dir.glob(pattern))
            logger.info("Found %d %s files in %s.", len(found), pattern, search_dir)
            candidate_files.extend(found)

    # Filter to files that look like PW exports; if none match heuristic, use all candidates
    pw_files = [f for f in candidate_files if _looks_like_pw_file(f)]
    if not pw_files and candidate_files:
        logger.info(
            "No files matched PW naming heuristics; treating all %d candidate files as PW exports.",
            len(candidate_files),
        )
        pw_files = candidate_files

    if not pw_files:
        logger.warning(
            "No portal export files found in %s.\n"
            "Manual instructions:\n"
            "  Export PW data from the FEMA PA portal and place files in:\n"
            "    data/raw/FEMA/  or  data/raw/fema_pa/\n"
            "  Accepted formats: .xlsx, .xls, .csv",
            [str(d) for d in search_dirs],
        )
        empty_df = pd.DataFrame(columns=PORTAL_COLUMNS)
        empty_df.to_parquet(out_path, index=False, engine="pyarrow")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    logger.info("Processing %d portal export file(s).", len(pw_files))
    all_frames: list[pd.DataFrame] = []

    for filepath in pw_files:
        raw_df = _read_file(filepath, logger)
        if raw_df is None or raw_df.empty:
            logger.warning("  Skipping empty or unreadable file: %s", filepath.name)
            continue
        normalized = _normalize_df(raw_df, filepath.name, logger)
        if not normalized.empty:
            all_frames.append(normalized)

    if not all_frames:
        logger.warning("All portal export files were empty or unreadable. Writing empty parquet.")
        empty_df = pd.DataFrame(columns=PORTAL_COLUMNS)
        empty_df.to_parquet(out_path, index=False, engine="pyarrow")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.concat(all_frames, ignore_index=True)
    logger.info("Combined %d rows before deduplication.", len(combined))

    # Deduplicate on pw_number + disaster_number (keep first occurrence)
    before_dedup = len(combined)
    has_pw = combined["pw_number"].notna() & (combined["pw_number"] != "")
    has_dr = combined["disaster_number"].notna() & (combined["disaster_number"] != "")
    dedup_mask = has_pw & has_dr
    deduplicated_part = combined[dedup_mask].drop_duplicates(
        subset=["pw_number", "disaster_number"], keep="first"
    )
    remainder = combined[~dedup_mask]
    combined = pd.concat([deduplicated_part, remainder], ignore_index=True)
    logger.info(
        "Deduplication: %d → %d rows (removed %d duplicates on pw_number+disaster_number).",
        before_dedup, len(combined), before_dedup - len(combined),
    )

    combined.to_parquet(out_path, index=False, engine="pyarrow")
    logger.info("Saved %d portal PW records to %s", len(combined), out_path)
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest FEMA PA portal export files and normalize to parquet."
    )
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output file exists.")
    args = parser.parse_args()

    result = run(force=args.force)
    logger = setup_logging("ingest_fema_pa_portal_exports")
    logger.info("Result: %s", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
