"""
Ingest Grants.gov daily XML extract files.

Place Grants.gov bulk XML extracts into data/raw/Grants/:
  GrantsDBExtract{YYYYMMDD}v2.xml

Output:
  data/staging/processed/pr_grants_opportunities.csv

Usage:
  python3 scripts/ingest_grants.py
  python3 scripts/ingest_grants.py --force
"""

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from scripts.config import PROJECT_ROOT, setup_logging

RAW_DIR = PROJECT_ROOT / "data" / "raw" / "Grants"

OUTPUT_COLUMNS = [
    "opportunity_id", "opportunity_number", "opportunity_title",
    "agency_code", "agency_name", "cfda_numbers",
    "opportunity_category",   # "D" = Discretionary, "M" = Mandatory, etc.
    "funding_instrument_type",  # "G" = Grant, "CA" = Cooperative Agreement, etc.
    "award_ceiling", "award_floor", "estimated_total_funding",
    "expected_award_count",
    "post_date", "close_date",
    "eligible_applicants",
    "description",
    "record_type",  # "synopsis" or "forecast"
    "source_file",
]

# Mapping from XML tag names to output column names, per element type
_SYNOPSIS_TAG = "OpportunitySynopsisDetail_1_0"
_FORECAST_TAG = "OpportunityForecastDetail_1_0"

_FIELD_MAP = {
    "OpportunityID":                     "opportunity_id",
    "OpportunityNumber":                 "opportunity_number",
    "OpportunityTitle":                  "opportunity_title",
    "AgencyCode":                        "agency_code",
    "AgencyName":                        "agency_name",
    "CFDANumbers":                       "cfda_numbers",
    "OpportunityCategory":               "opportunity_category",
    "FundingInstrumentType":             "funding_instrument_type",
    "AwardCeiling":                      "award_ceiling",
    "AwardFloor":                        "award_floor",
    "EstimatedTotalProgramFunding":      "estimated_total_funding",
    "ExpectedNumberOfAwards":            "expected_award_count",
    "PostDate":                          "post_date",
    "CloseDate":                         "close_date",
    "EligibleApplicants":                "eligible_applicants",
    "AdditionalInformationOnEligibility": None,  # not in output columns, skip
    "Description":                       "description",
}


def _parse_element(elem, record_type: str, source_file: str) -> dict:
    """Extract fields from a single OpportunitySynopsisDetail or OpportunityForecastDetail element."""
    row = {col: "" for col in OUTPUT_COLUMNS}
    row["record_type"] = record_type
    row["source_file"] = source_file
    for child in elem:
        col = _FIELD_MAP.get(child.tag)
        if col is not None:
            row[col] = (child.text or "").strip()
    return row


def _parse_xml_file(xml_path: Path, logger) -> list[dict]:
    """Stream-parse a Grants.gov XML extract, returning a list of row dicts."""
    rows = []
    logger.info(f"  Parsing {xml_path.name}...")
    source_file = xml_path.name
    try:
        with open(xml_path, "rb") as f:
            for event, elem in ET.iterparse(f, events=("end",)):
                if elem.tag == _SYNOPSIS_TAG:
                    rows.append(_parse_element(elem, "synopsis", source_file))
                    elem.clear()
                elif elem.tag == _FORECAST_TAG:
                    rows.append(_parse_element(elem, "forecast", source_file))
                    elem.clear()
    except ET.ParseError as e:
        logger.warning(f"  XML parse error in {xml_path.name}: {e}")
    logger.info(f"    {xml_path.name}: {len(rows):,} records")
    return rows


def run(root: Path = None, force: bool = False) -> dict:
    if root is None:
        root = PROJECT_ROOT
    root = Path(root)
    raw_dir = root / "data" / "raw" / "Grants"
    out_path = root / "data" / "staging" / "processed" / "pr_grants_opportunities.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    logger = setup_logging("ingest_grants")

    if not force and out_path.exists():
        existing = pd.read_csv(out_path, dtype=str, low_memory=False)
        if len(existing) > 0:
            logger.info(f"  Cached — {len(existing):,} rows in {out_path.name}")
            return {"rows": len(existing), "path": str(out_path), "status": "CACHED"}

    if not raw_dir.exists():
        logger.info(f"  No Grants raw dir at {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    xml_files = sorted(raw_dir.glob("*.xml"))
    if not xml_files:
        logger.info(f"  No XML files in {raw_dir} — skipping ingest")
        return {"rows": 0, "path": str(out_path), "status": "NO_FILES"}

    logger.info(f"  Found {len(xml_files)} Grants.gov XML file(s) in {raw_dir}")

    all_rows = []
    for xml_path in xml_files:
        rows = _parse_xml_file(xml_path, logger)
        all_rows.extend(rows)

    if not all_rows:
        logger.warning("  No parseable Grants.gov XML data found — writing empty schema")
        pd.DataFrame(columns=OUTPUT_COLUMNS).to_csv(out_path, index=False, encoding="utf-8")
        return {"rows": 0, "path": str(out_path), "status": "EMPTY"}

    combined = pd.DataFrame(all_rows, columns=OUTPUT_COLUMNS)

    # Deduplicate on opportunity_id across files — keep row with latest post_date
    before = len(combined)
    has_id = combined["opportunity_id"].str.strip().ne("")
    with_id = combined[has_id].copy()
    without_id = combined[~has_id].copy()

    if not with_id.empty:
        # Coerce post_date to sortable string (MMDDYYYY or empty); sort so latest is first
        with_id["_post_date_sort"] = pd.to_datetime(
            with_id["post_date"], format="%m%d%Y", errors="coerce"
        )
        with_id = with_id.sort_values("_post_date_sort", ascending=False, na_position="last")
        with_id = with_id.drop_duplicates(subset=["opportunity_id"], keep="first")
        with_id = with_id.drop(columns=["_post_date_sort"])

    combined = pd.concat([with_id, without_id], ignore_index=True)
    removed = before - len(combined)
    if removed:
        logger.info(f"  Removed {removed:,} duplicate opportunity_id rows (kept latest post_date)")

    combined.to_csv(out_path, index=False, encoding="utf-8")
    logger.info(f"  Written: {out_path.name} ({len(combined):,} rows)")
    return {"rows": len(combined), "path": str(out_path), "status": "OK"}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Ingest Grants.gov daily XML extract files from data/raw/Grants/"
    )
    parser.add_argument("--force", action="store_true", help="Re-ingest even if output exists")
    args = parser.parse_args()
    result = run(force=args.force)
    print(f"\nGrants.gov ingest: {result['rows']:,} rows — {result['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
