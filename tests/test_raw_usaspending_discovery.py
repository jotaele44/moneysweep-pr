"""Tests for R4.9H raw USAspending discovery."""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from moneysweep.pipeline.raw_usaspending_discovery import (
    run_raw_usaspending_discovery,
)

CANONICAL_COLUMNS = [
    "award_id",
    "recipient_name",
    "recipient_name_normalized",
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
    "source_system",
    "source_record_id",
    "source_lineage_path",
    "source_lineage_mode",
]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _csv_text(rows: list[dict], fieldnames: list[str]) -> str:
    from io import StringIO

    handle = StringIO()
    writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return handle.getvalue()


def _csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _bootstrap(tmp_path: Path) -> None:
    raw_zip = tmp_path / "data" / "raw" / "USAS.zip"
    raw_zip.parent.mkdir(parents=True, exist_ok=True)

    exact_grants = [
        {
            "award_id": "GRANT-1",
            "recipient_name": "Puerto Rico Recipient",
            "recipient_name_normalized": "PUERTO RICO RECIPIENT",
            "recipient_uei": "",
            "awarding_agency": "HHS",
            "awarding_sub_agency": "",
            "obligated_amount": "100",
            "award_date": "2024-01-01",
            "fiscal_year": "2024",
            "pop_state": "PR",
            "pop_county": "",
            "description": "grant",
            "source_file": "raw_grants_exact.csv",
            "source_dataset": "grants",
            "award_category": "grant",
            "source_system": "usaspending_raw",
            "source_record_id": "raw:GRANT-1",
            "source_lineage_path": "data/raw/USAS.zip::USAS/data/raw_grants_exact.csv",
            "source_lineage_mode": "r4_9h_exact",
        }
    ]
    unmappable = [
        {
            "dataset": "federal_edges",
            "vendor_name": "Vendor",
            "agency_name": "Agency",
            "sub_agency": "Sub Agency",
            "contract_id": "RAW-1",
            "award_date": "2024-01-01",
            "fiscal_year": "2024",
            "amount_usd": "100",
            "source_file": "All_Assistance_PrimeTransactions.csv",
            "normalized_vendor": "VENDOR",
        }
    ]
    contracts = [
        {
            "contract_id": "CONT-1",
            "vendor_name": "Already Validated",
            "agency_name": "GSA",
            "award_date": "2024-01-01",
            "obligated_amount": "10",
            "pop_state": "PR",
            "source_file": "contracts.csv",
            "fiscal_year": "2024",
        }
    ]
    with zipfile.ZipFile(raw_zip, "w") as zf:
        zf.writestr("USAS/data/raw_grants_exact.csv", _csv_text(exact_grants, CANONICAL_COLUMNS))
        zf.writestr(
            "USAS/data/canonical/federal_spending_canonical.csv",
            _csv_text(unmappable, list(unmappable[0].keys())),
        )
        zf.writestr(
            "USAS/data/raw_contracts_already_done.csv",
            _csv_text(contracts, list(contracts[0].keys())),
        )

    checklist_rows = [
        {
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/contracts.csv",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "accepted_filename_patterns": "*.csv",
            "required_columns": "contract_id|vendor_name|agency_name|award_date|obligated_amount|pop_state|source_file|fiscal_year",
            "validation_command": "echo contracts",
            "unfreeze_condition": "already validated",
            "reason_blocked": "",
        },
        {
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/grants.csv",
            "target_output_path": "data/staging/processed/pr_grants_master.csv",
            "accepted_filename_patterns": "*.csv",
            "required_columns": "|".join(CANONICAL_COLUMNS),
            "validation_command": "echo grants",
            "unfreeze_condition": "deliver grants",
            "reason_blocked": "file_not_delivered",
        },
        {
            "expected_input": "data/staging/processed/pr_subawards_master.csv",
            "source_family": "fsrs_subawards",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": "data/manual_import_dropzone/subawards.csv",
            "target_output_path": "data/staging/processed/pr_subawards_master.csv",
            "accepted_filename_patterns": "*.csv",
            "required_columns": "|".join(CANONICAL_COLUMNS),
            "validation_command": "echo subawards",
            "unfreeze_condition": "deliver subawards",
            "reason_blocked": "file_not_delivered",
        },
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv",
        checklist_rows,
        list(checklist_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "sources_still_blocked_r4_9g.csv",
        [
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "blocker_class": "manual_file_required",
                "target_dropzone_path": "data/manual_import_dropzone/contracts.csv",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "blocker_reason": "should be filtered because already validated",
                "next_action": "none",
                "validation_command": "echo contracts",
                "unfreeze_condition": "already validated",
                "r4_9g_status": "still_blocked",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "expected_input": "data/staging/processed/pr_grants_master.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "blocker_class": "manual_file_required",
                "target_dropzone_path": "data/manual_import_dropzone/grants.csv",
                "target_output_path": "data/staging/processed/pr_grants_master.csv",
                "blocker_reason": "candidate_missing_required_columns",
                "next_action": "await_valid_source_delivery",
                "validation_command": "echo grants",
                "unfreeze_condition": "deliver grants",
                "r4_9g_status": "still_blocked",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "expected_input": "data/staging/processed/pr_subawards_master.csv",
                "source_family": "fsrs_subawards",
                "blocker_class": "manual_file_required",
                "target_dropzone_path": "data/manual_import_dropzone/subawards.csv",
                "target_output_path": "data/staging/processed/pr_subawards_master.csv",
                "blocker_reason": "candidate_missing_required_columns",
                "next_action": "await_valid_source_delivery",
                "validation_command": "echo subawards",
                "unfreeze_condition": "deliver subawards",
                "r4_9g_status": "still_blocked",
            },
        ],
        [
            "generated_at",
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "blocker_reason",
            "next_action",
            "validation_command",
            "unfreeze_condition",
            "r4_9g_status",
        ],
    )
    _write_csv(
        tmp_path / "data" / "exports" / "scoped_unfreeze_candidates_r4_9g.csv",
        [
            {
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "validation_status": "validated",
            }
        ],
        ["expected_input", "validation_status"],
    )
    _write_json(
        tmp_path / "data" / "exports" / "scoped_unfreeze_status_r4_9g.json",
        {
            "r4_9g_gate_passed": True,
            "r4_9g_candidates_validated": 1,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
        },
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_recovery_resume_conditions_r4_9z.csv",
        [],
        ["expected_input"],
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
            "downstream_phases_blocked": True,
        },
    )


def test_raw_usaspending_discovery_validates_only_blocked_targets(tmp_path: Path):
    _bootstrap(tmp_path)

    status = run_raw_usaspending_discovery(tmp_path)

    assert status["r4_9h_gate_passed"] is True
    assert status["r4_9h_raw_files_scanned"] == 4
    assert status["r4_9h_usaspending_like_files_found"] == 4
    assert status["r4_9h_candidate_matches"] == 3
    assert status["r4_9h_candidates_validated"] == 1
    assert status["r4_9h_candidates_rejected"] == 2
    assert status["r4_9h_new_unfreeze_candidates"] == 1
    assert status["r4_9h_sources_still_blocked"] == 1
    assert status["r4_9h_downloads_executed"] is False
    assert status["r4_9h_endpoint_retries_executed"] is False
    assert status["r4_9h_rows_ingested"] == 0
    assert status["r4_9h_production_inputs_staged"] == 0
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True
    assert status["downstream_phases_blocked"] is True

    unfreeze_rows = _csv_rows(
        tmp_path / "data" / "review_queue" / "raw_usaspending_unfreeze_candidates_r4_9h.csv"
    )
    assert len(unfreeze_rows) == 1
    assert unfreeze_rows[0]["expected_input"] == "data/staging/processed/pr_grants_master.csv"
    assert unfreeze_rows[0]["validation_reason"] == "exact_required_columns_present"

    rejected_rows = _csv_rows(
        tmp_path / "data" / "review_queue" / "raw_usaspending_rejected_candidates_r4_9h.csv"
    )
    assert len(rejected_rows) == 2
    assert all("pop_state" in row["missing_columns"] for row in rejected_rows)
    assert all(
        row["expected_input"] != "data/staging/processed/pr_contracts_master.csv"
        for row in rejected_rows
    )


def test_raw_usaspending_discovery_passes_with_no_raw_candidates(tmp_path: Path):
    _bootstrap(tmp_path)
    (tmp_path / "data" / "raw" / "USAS.zip").unlink()
    (tmp_path / "data" / "raw" / "notes.txt").write_text("not a supported source", encoding="utf-8")

    status = run_raw_usaspending_discovery(tmp_path)

    assert status["r4_9h_gate_passed"] is True
    assert status["r4_9h_raw_files_scanned"] == 0
    assert status["r4_9h_candidate_matches"] == 0
    assert status["r4_9h_new_unfreeze_candidates"] == 0
    assert status["r4_9h_sources_still_blocked"] == 2
