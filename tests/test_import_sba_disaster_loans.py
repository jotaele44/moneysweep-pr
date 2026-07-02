"""Tests for scripts.import_sba_disaster_loans.

The fixture workbook is generated on the fly with pandas/openpyxl (no binary
.xlsx committed to the repo), mirroring the on-the-fly-fixture convention used
by tests/test_act_acuden_extractor.py. It reproduces the real workbook's shape:
a couple of junk title rows before the true header (to exercise
detect_header_row) and both the "FY22 Home" and "FY22 Business" sheets.
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pandas as pd
import pytest

from moneysweep.validation.canonical_v1_schema import validate_row
from scripts.import_sba_disaster_loans import (
    HOME_MARKERS,
    SOURCE_ID,
    build_municipality_rollup,
    clean_amount,
    detect_header_row,
    import_workbook,
    make_record_id,
    normalize_municipality,
    write_jsonl,
    write_municipality_rollup,
    write_summary,
)

SCHEMA_PATH = Path("schemas/sba_recovery_loan.schema.json")

HOME_HEADER = [
    "SBA Physical Declaration Number",
    "FEMA Disaster Number",
    "SBA Disaster Number",
    "Damaged Property City",
    "Damaged Property Zip Code",
    "County",
    "Total Verified Loss",
    "Total Approved Loan Amount",
]

BUSINESS_HEADER = [
    "SBA EIDL Declaration Number",
    "FEMA Disaster Number",
    "SBA Disaster Number",
    "Damaged Property City",
    "Damaged Property Zip Code",
    "Damaged Property County",
    "Verified Loss",
    "Approved Amount",
    "EIDL Amount",
]


def _pad(row: list, width: int) -> list:
    return row + [None] * (width - len(row))


def _build_workbook(path: Path) -> None:
    home_rows = [
        _pad(["SBA Disaster Loan Data"], len(HOME_HEADER)),
        _pad(["Fiscal Year 2022 Home Loans"], len(HOME_HEADER)),
        HOME_HEADER,
        # normal record
        ["12345", "4339", "12345", "San Juan", "00901", "SAN JUAN", 50000, 45000],
        # municipality needing accent normalization + "$"/comma-formatted amount
        ["12346", "4339", "12345", "Bayamon", "00956", "BAYAMON", 12000, "$12,345.67"],
        # missing municipality -> must be dropped
        ["12347", "4339", "12345", "Ponce", "00730", None, 8000, 7000],
        # missing approved amount -> must default to 0.0; same municipality as
        # the first row so the rollup test can assert aggregation across rows
        ["12348", "4339", "12345", "San Juan", "00901", "SAN JUAN", 3000, None],
    ]
    business_rows = [
        _pad(["SBA Disaster Loan Data"], len(BUSINESS_HEADER)),
        BUSINESS_HEADER,
        ["B100", "4339", "12345", "Mayaguez", "00680", "MAYAGUEZ", 20000, 18000, 5000],
    ]
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        pd.DataFrame(home_rows).to_excel(writer, sheet_name="FY22 Home", header=False, index=False)
        pd.DataFrame(business_rows).to_excel(
            writer, sheet_name="FY22 Business", header=False, index=False
        )


@pytest.fixture
def workbook(tmp_path: Path) -> Path:
    path = tmp_path / "sba_disaster_loans_pr.xlsx"
    _build_workbook(path)
    return path


@pytest.fixture(scope="module")
def schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Unit: helper functions
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_clean_amount_variants():
    assert clean_amount(1234.5) == 1234.5
    assert clean_amount("$12,345.67") == 12345.67
    assert clean_amount("-") is None
    assert clean_amount(float("nan")) is None


@pytest.mark.unit
def test_normalize_municipality_applies_accent_map():
    assert normalize_municipality("bayamon") == "BAYAMÓN"
    assert normalize_municipality("  San Juan  ") == "SAN JUAN"
    assert normalize_municipality(None) is None


@pytest.mark.unit
def test_make_record_id_is_deterministic():
    record = {
        "loan_type": "home",
        "fema_disaster_number": "4339",
        "sba_disaster_number": "12345",
        "municipality": "SAN JUAN",
        "zip_code": "00901",
        "approved_loan_amount": 45000,
        "raw_sheet": "FY22 Home",
        "raw_row_number": 4,
    }
    assert make_record_id(record) == make_record_id(dict(record))
    other = dict(record, municipality="PONCE")
    assert make_record_id(record) != make_record_id(other)


@pytest.mark.unit
def test_detect_header_row_skips_junk_rows(workbook: Path):
    assert detect_header_row(workbook, "FY22 Home", HOME_MARKERS) == 2


# ---------------------------------------------------------------------------
# Integration: end-to-end import
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_import_workbook_filters_and_defaults(workbook: Path):
    records = import_workbook(workbook)
    # 4 home rows in, 1 dropped for missing municipality -> 3; + 1 business row.
    assert len(records) == 4
    declaration_numbers = {r.get("physical_declaration_number") for r in records}
    assert "12347" not in declaration_numbers

    accent_row = next(r for r in records if r["physical_declaration_number"] == "12346")
    assert accent_row["municipality"] == "BAYAMÓN"
    assert accent_row["approved_loan_amount"] == 12345.67

    defaulted_row = next(r for r in records if r["physical_declaration_number"] == "12348")
    assert defaulted_row["approved_loan_amount"] == 0.0
    assert defaulted_row["municipality"] == "SAN JUAN"

    business_row = next(r for r in records if r["loan_type"] == "business")
    assert business_row["municipality"] == "MAYAGÜEZ"
    assert business_row["eidl_amount"] == 5000


@pytest.mark.integration
def test_records_validate_against_schema(workbook: Path, schema: dict):
    records = import_workbook(workbook)
    assert records
    for record in records:
        assert record["source_id"] == SOURCE_ID
        errors = validate_row(record, schema)
        assert errors == [], errors


@pytest.mark.integration
def test_records_carry_relationship_keys(workbook: Path):
    """Every emitted record must be joinable by FEMA disaster number and
    municipality — these foreign-key fields ARE the REFERENCES_FEMA_DISASTER /
    ROLLS_UP_TO_MUNICIPALITY relationships (see docs/SBA_RECOVERY_SOURCE_REFRESH.md)."""
    records = import_workbook(workbook)
    for record in records:
        assert record["fema_disaster_number"]
        assert record["municipality"]


@pytest.mark.integration
def test_import_is_deterministic(workbook: Path):
    first = import_workbook(workbook)
    second = import_workbook(workbook)
    assert [r["record_id"] for r in first] == [r["record_id"] for r in second]


# ---------------------------------------------------------------------------
# Integration: output writers
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_write_jsonl_round_trips(workbook: Path, tmp_path: Path):
    records = import_workbook(workbook)
    out_path = tmp_path / "out.jsonl"
    write_jsonl(out_path, records)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(records)
    assert all(json.loads(line)["source_id"] == SOURCE_ID for line in lines)


@pytest.mark.integration
def test_write_summary_reports_correct_totals(workbook: Path, tmp_path: Path):
    records = import_workbook(workbook)
    summary_path = tmp_path / "summary.md"
    write_summary(summary_path, records)
    text = summary_path.read_text(encoding="utf-8")
    assert f"| Total records | {len(records):,} |" in text
    municipalities = {r["municipality"] for r in records}
    assert f"| Municipalities | {len(municipalities):,} |" in text


@pytest.mark.unit
def test_build_municipality_rollup_aggregates_across_rows(workbook: Path):
    records = import_workbook(workbook)
    rollup = {row["municipality"]: row for row in build_municipality_rollup(records)}

    san_juan = rollup["SAN JUAN"]
    assert san_juan["loan_count"] == 2
    assert san_juan["home_loan_count"] == 2
    assert san_juan["business_loan_count"] == 0
    assert math.isclose(san_juan["total_approved_loan_amount"], 45000.0)
    assert math.isclose(san_juan["total_verified_loss_amount"], 53000.0)

    mayaguez = rollup["MAYAGÜEZ"]
    assert mayaguez["business_loan_count"] == 1
    assert math.isclose(mayaguez["total_approved_loan_amount"], 18000.0)


@pytest.mark.integration
def test_write_municipality_rollup_writes_expected_csv(workbook: Path, tmp_path: Path):
    records = import_workbook(workbook)
    out_path = tmp_path / "rollup.csv"
    write_municipality_rollup(out_path, records)
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    municipalities = {row["municipality"] for row in rows}
    assert municipalities == {r["municipality"] for r in records}
    san_juan = next(row for row in rows if row["municipality"] == "SAN JUAN")
    assert int(san_juan["loan_count"]) == 2
