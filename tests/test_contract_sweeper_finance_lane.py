import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from contract_sweeper.validation.canonical_v1_schema import validate_row  # noqa: E402
from readiness.contract_sweeper_finance_lane import (  # noqa: E402
    EXPORT_CONTRACT_VERSION,
    FINANCE_FIELDS,
    ContractSweeperFinanceLaneError,
    build_contract_sweeper_finance_lane,
)

_REPORT_SCHEMA = Path(__file__).resolve().parents[1] / (
    "schemas/contract_sweeper_finance_lane_report.schema.json"
)

# the real router derivative columns (from scripts/route_pr_intake.py output)
DERIVATIVE_COLUMNS = [
    "record_id",
    "source_item_id",
    "canonical_repo",
    "related_repo_record_id",
    "source_name",
    "source_url",
    "published_at",
    "discovered_at",
    "title",
    "summary_own_words",
    "agency_entity",
    "municipality_name",
    "location_text",
    "domains",
    "output_tables",
    "evidence_tier",
    "confidence_level",
    "source_hash",
    "content_hash",
    "dedupe_group_id",
    "final_status",
    "latitude",
    "longitude",
    "asset_type",
    "dataset_type",
    "file_format",
    "target_repo",
]


def _row(**over):
    base = {c: "" for c in DERIVATIVE_COLUMNS}
    base.update(
        {
            "record_id": "CS-1",
            "source_item_id": "RAW-1",
            "canonical_repo": "Contract-Sweeper",
            "source_name": "DTOP",
            "title": "Award notice",
            "evidence_tier": "T2",
            "confidence_level": "High",
            "target_repo": "Contract-Sweeper",
            "domains": json.dumps(["public_funding"]),
            "output_tables": json.dumps(["funding_event_leads", "verification_queue"]),
        }
    )
    base.update(over)
    return base


def _write(tmp_path, rows):
    p = tmp_path / "contract_sweeper_derivatives.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DERIVATIVE_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    return tmp_path


def _read(path):
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_missing_input_raises(tmp_path):
    with pytest.raises(ContractSweeperFinanceLaneError):
        build_contract_sweeper_finance_lane(tmp_path)


def test_row_routes_to_named_tables(tmp_path):
    report = build_contract_sweeper_finance_lane(_write(tmp_path, [_row()]), tmp_path / "out")
    assert report["by_table"]["funding_event_leads"] == 1
    assert report["by_review_queue"]["verification_queue"] == 1
    assert report["discrepancy_count"] == 0 and report["zero_loss_pass"]
    funding = _read(tmp_path / "out" / "data" / "normalized" / "funding_event_leads.csv")
    assert funding[0]["record_id"] == "CS-1"


def test_multi_table_fanout(tmp_path):
    row = _row(
        record_id="CS-2",
        domains=json.dumps(["contracts", "public_funding"]),
        output_tables=json.dumps(
            [
                "contracts_procurement_events",
                "funding_event_leads",
                "contract_sweeper_crosswalk_queue",
                "verification_queue",
            ]
        ),
    )
    report = build_contract_sweeper_finance_lane(_write(tmp_path, [row]), tmp_path / "out")
    assert report["by_table"]["contracts_procurement_events"] == 1
    assert report["by_table"]["funding_event_leads"] == 1
    assert report["by_review_queue"]["contract_sweeper_crosswalk_queue"] == 1
    assert report["by_review_queue"]["verification_queue"] == 1


def test_empty_domains_goes_to_discrepancy(tmp_path):
    report = build_contract_sweeper_finance_lane(
        _write(tmp_path, [_row(domains="[]")]), tmp_path / "out"
    )
    assert report["discrepancy_count"] == 1 and report["zero_loss_pass"]
    disc = _read(tmp_path / "out" / "data" / "review" / "discrepancy_queue.csv")
    assert "empty array" in disc[0]["review_reason"]


def test_unrecognized_output_tables_goes_to_discrepancy(tmp_path):
    report = build_contract_sweeper_finance_lane(
        _write(tmp_path, [_row(output_tables=json.dumps(["bogus_table"]))]), tmp_path / "out"
    )
    assert report["discrepancy_count"] == 1


def test_missing_record_id_goes_to_discrepancy(tmp_path):
    report = build_contract_sweeper_finance_lane(
        _write(tmp_path, [_row(record_id="")]), tmp_path / "out"
    )
    assert report["discrepancy_count"] == 1


def test_zero_loss_accounting(tmp_path):
    rows = [
        _row(record_id="A"),
        _row(record_id="B", domains="[]"),  # -> discrepancy
        _row(
            record_id="C",
            domains=json.dumps(["politics"]),
            output_tables=json.dumps(["politics_finance_items"]),
        ),
    ]
    report = build_contract_sweeper_finance_lane(_write(tmp_path, rows), tmp_path / "out")
    assert report["input_rows"] == 3
    assert report["routed_rows"] + report["discrepancy_count"] == 3
    assert report["zero_loss_pass"]


def test_finance_records_carry_no_geometry(tmp_path):
    build_contract_sweeper_finance_lane(_write(tmp_path, [_row()]), tmp_path / "out")
    funding = _read(tmp_path / "out" / "data" / "normalized" / "funding_event_leads.csv")
    assert set(funding[0].keys()) == set(FINANCE_FIELDS)
    assert "latitude" not in funding[0] and "longitude" not in funding[0]


# --------------------------------------------------------------------------- #
# Report-contract hardening (Wave E)
# --------------------------------------------------------------------------- #


def test_report_pins_export_contract_version():
    """The finance-lane report contract is 1.0.0 — bumping it is a deliberate,
    cross-repo-coordinated act, so lock it down here (see schemas/README.md)."""
    assert EXPORT_CONTRACT_VERSION == "1.0.0"


def test_emitted_report_conforms_to_schema(tmp_path):
    """An emitted report validates against its draft-07 schema (via the repo's
    stdlib validator) and carries the pinned contract version."""
    report = build_contract_sweeper_finance_lane(_write(tmp_path, [_row()]), tmp_path / "out")
    schema = json.loads(_REPORT_SCHEMA.read_text(encoding="utf-8"))

    errors = validate_row(report, schema)
    assert errors == [], f"emitted report violates its schema: {errors}"

    # The report's own contract version must match the module constant.
    assert report["export_contract_version"] == EXPORT_CONTRACT_VERSION == "1.0.0"

    # Schema must enumerate exactly the keys the builder emits (no drift either way).
    assert set(schema["required"]) == set(report)
