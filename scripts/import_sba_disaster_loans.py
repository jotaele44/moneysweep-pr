#!/usr/bin/env python3
"""Import Puerto Rico SBA loan workbook into canonical JSONL records."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

SOURCE_ID = "sba_disaster_loans_pr"
DEFAULT_INPUT = Path("data/manual/sba_disaster_loans/sba_disaster_loans_pr.xlsx")
DEFAULT_OUTPUT = Path("data/staging/processed/sba_recovery_loans_pr.jsonl")
DEFAULT_SUMMARY = Path("reports/sba_recovery_import_summary.md")

HOME_MARKERS = {"SBA Physical Declaration Number", "FEMA Disaster Number", "SBA Disaster Number"}
BUSINESS_MARKERS = {"SBA EIDL Declaration Number", "FEMA Disaster Number", "SBA Disaster Number"}

COLUMN_ALIASES = {
    "SBA Physical Declaration Number": "physical_declaration_number",
    "SBA EIDL Declaration Number": "eidl_declaration_number",
    "FEMA Disaster Number": "fema_disaster_number",
    "SBA Disaster Number": "sba_disaster_number",
    "Damaged Property City": "damaged_property_city",
    "Damaged Property Zip Code": "zip_code",
    "Damaged Property County": "municipality",
    "County": "municipality",
    "Verified Loss": "verified_loss_amount",
    "Total Verified Loss": "verified_loss_amount",
    "Approved Amount": "approved_loan_amount",
    "Total Approved Loan Amount": "approved_loan_amount",
    "EIDL Amount": "eidl_amount",
}

MUNICIPALITY_REPLACEMENTS = {
    "ANASCO": "AÑASCO",
    "BAYAMON": "BAYAMÓN",
    "CANOVANAS": "CANÓVANAS",
    "CATANO": "CATAÑO",
    "COMERIO": "COMERÍO",
    "GUANICA": "GUÁNICA",
    "JUANA DIAZ": "JUANA DÍAZ",
    "LAS MARIAS": "LAS MARÍAS",
    "LOIZA": "LOÍZA",
    "MAYAGUEZ": "MAYAGÜEZ",
    "PENUELAS": "PEÑUELAS",
    "RIO GRANDE": "RÍO GRANDE",
    "SAN GERMAN": "SAN GERMÁN",
    "SAN SEBASTIAN": "SAN SEBASTIÁN",
}


def clean_string(value: Any) -> str | None:
    if pd.isna(value):
        return None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null"}:
        return None
    return text


def clean_amount(value: Any) -> float | None:
    if pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[$,\s]", "", str(value).strip())
    if text in {"", "-", "nan", "None"}:
        return None
    return float(text)


def normalize_municipality(value: Any) -> str | None:
    text = clean_string(value)
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text.upper()).strip()
    return MUNICIPALITY_REPLACEMENTS.get(normalized, normalized)


def detect_header_row(path: Path, sheet_name: str, markers: set[str], max_rows: int = 40) -> int:
    preview = pd.read_excel(path, sheet_name=sheet_name, header=None, nrows=max_rows)
    for idx, row in preview.iterrows():
        values = {clean_string(value) for value in row.tolist()}
        values.discard(None)
        if len(markers.intersection(values)) >= 2:
            return int(idx)
    raise ValueError(f"Could not detect header row for {sheet_name}")


def make_record_id(record: dict[str, Any]) -> str:
    key_fields = [
        "loan_type",
        "fema_disaster_number",
        "sba_disaster_number",
        "municipality",
        "zip_code",
        "approved_loan_amount",
        "raw_sheet",
        "raw_row_number",
    ]
    key = "|".join(str(record.get(field) or "") for field in key_fields)
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def normalize_sheet(
    path: Path, sheet_name: str, loan_type: str, markers: set[str]
) -> list[dict[str, Any]]:
    header_row = detect_header_row(path, sheet_name, markers)
    df = pd.read_excel(path, sheet_name=sheet_name, header=header_row)
    df.columns = [str(col).strip() for col in df.columns]
    columns = list(df.columns)

    records: list[dict[str, Any]] = []
    for row_idx, row in df.iterrows():
        record: dict[str, Any] = {
            "source_id": SOURCE_ID,
            "source_file": path.name,
            "loan_type": loan_type,
            "raw_sheet": sheet_name,
            "raw_row_number": int(row_idx) + header_row + 2,
            "fiscal_year": 2022,
            "report_run_date": "2023-03-16",
            "evidence_tier": "T1",
            "confidence": 0.95,
            "physical_declaration_number": None,
            "eidl_declaration_number": None,
            "fema_disaster_number": None,
            "sba_disaster_number": None,
            "damaged_property_city": None,
            "zip_code": None,
            "municipality": None,
            "verified_loss_amount": None,
            "approved_loan_amount": None,
            "eidl_amount": None,
        }
        for source_col, target_col in COLUMN_ALIASES.items():
            if source_col in columns:
                record[target_col] = row.get(source_col)

        for field in (
            "physical_declaration_number",
            "eidl_declaration_number",
            "fema_disaster_number",
            "sba_disaster_number",
            "damaged_property_city",
            "zip_code",
        ):
            record[field] = clean_string(record.get(field))
        record["municipality"] = normalize_municipality(record.get("municipality"))
        for field in ("verified_loss_amount", "approved_loan_amount", "eidl_amount"):
            record[field] = clean_amount(record.get(field))

        if not record.get("fema_disaster_number") and not record.get("sba_disaster_number"):
            continue
        if not record.get("municipality"):
            continue
        if record.get("approved_loan_amount") is None:
            record["approved_loan_amount"] = 0.0
        record["record_id"] = make_record_id(record)
        records.append(record)
    return records


def import_workbook(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Input workbook not found: {path}")
    records: list[dict[str, Any]] = []
    records.extend(normalize_sheet(path, "FY22 Home", "home", HOME_MARKERS))
    records.extend(normalize_sheet(path, "FY22 Business", "business", BUSINESS_MARKERS))
    return records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_summary(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    approved = sum(float(record.get("approved_loan_amount") or 0) for record in records)
    verified = sum(float(record.get("verified_loss_amount") or 0) for record in records)
    municipalities = {
        record.get("municipality") for record in records if record.get("municipality")
    }
    lines = [
        "# SBA Recovery Loan Import Summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total records | {len(records):,} |",
        f"| Municipalities | {len(municipalities):,} |",
        f"| Approved amount | ${approved:,.2f} |",
        f"| Verified loss | ${verified:,.2f} |",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    records = import_workbook(args.input)
    write_jsonl(args.output, records)
    write_summary(args.summary, records)


if __name__ == "__main__":
    main()
