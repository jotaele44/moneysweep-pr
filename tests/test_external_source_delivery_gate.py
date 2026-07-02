"""Tests for R4.9C external source delivery gate."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from moneysweep.pipeline.external_source_delivery_gate import (
    run_external_source_delivery_gate,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        digest.update(handle.read())
    return digest.hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _bootstrap_r49c(tmp_path: Path, *, include_delivered_file: bool) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "source_materialization_status_r4_9b.json",
        {
            "r4_9b_manifest_records_checked": 1,
            "r4_9b_files_materialized": 0,
            "r4_9b_files_hash_validated": 0,
            "r4_9b_materialization_blockers": 1,
            "r4_9b_forbidden_artifact_usage": False,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
        },
    )
    _write_csv(
        tmp_path / "data" / "exports" / "source_materialization_results_r4_9b.csv",
        [
            {
                "manifest_index": "1",
                "source_system": "federal_sectoral_doe",
                "target_output_path": "data/staging/processed/pr_doe_master.csv",
                "target_output_abs": str(tmp_path / "data/staging/processed/pr_doe_master.csv"),
                "source_file": "data/staging/processed/pr_doe_master.csv",
                "manifest_path": "data/manifests/r4_8d/12_pr_doe_master.manifest.json",
                "expected_row_count": "1",
                "expected_sha256": "x",
                "validation_status": "validated",
                "manifest_type": "validated_source_manifest",
                "manifest_record_valid": "True",
                "materialization_status": "blocked",
                "copy_performed": "False",
                "candidate_used": "",
                "candidate_source_path": "",
                "target_exists": "False",
                "target_row_count": "0",
                "target_sha256": "",
                "hash_validated": "False",
                "row_validated_nonzero": "False",
                "blocker_reason": "no_hash_compatible_candidate_found",
            }
        ],
        [
            "manifest_index",
            "source_system",
            "target_output_path",
            "target_output_abs",
            "source_file",
            "manifest_path",
            "expected_row_count",
            "expected_sha256",
            "validation_status",
            "manifest_type",
            "manifest_record_valid",
            "materialization_status",
            "copy_performed",
            "candidate_used",
            "candidate_source_path",
            "target_exists",
            "target_row_count",
            "target_sha256",
            "hash_validated",
            "row_validated_nonzero",
            "blocker_reason",
        ],
    )
    _write_json(
        tmp_path / "data" / "exports" / "partial_rebuild_retry_status_r4_9b.json",
        {
            "r4_9b_gate_passed": True,
            "r4_9b_rebuild_attempted": False,
            "r4_9b_rebuild_succeeded": False,
            "r4_9b_output_status": "BLOCKED_DIAGNOSTIC",
        },
    )
    _write_csv(
        tmp_path / "data" / "exports" / "partial_rebuild_retry_inputs_r4_9b.csv",
        [],
        [
            "expected_input",
            "source_dataset",
            "mapped_rel",
            "mapped_abs",
            "mapping_mode",
            "input_status",
            "row_count",
            "sha256",
            "source_system",
            "source_file",
            "source_manifest_path",
            "target_output_path",
            "lineage_path",
            "reason",
        ],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_materialization_blockers_r4_9b.csv",
        [
            {
                "manifest_index": "1",
                "source_system": "federal_sectoral_doe",
                "target_output_path": "data/staging/processed/pr_doe_master.csv",
                "source_file": "data/staging/processed/pr_doe_master.csv",
                "manifest_path": "data/manifests/r4_8d/12_pr_doe_master.manifest.json",
                "blocker_reason": "no_hash_compatible_candidate_found",
                "next_action": "external_acquisition_or_manual_file",
            }
        ],
        [
            "manifest_index",
            "source_system",
            "target_output_path",
            "source_file",
            "manifest_path",
            "blocker_reason",
            "next_action",
        ],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "partial_rebuild_retry_blockers_r4_9b.csv",
        [
            {
                "blocker_type": "source_materialization",
                "source_system": "federal_sectoral_doe",
                "expected_input": "data/staging/processed/pr_doe_master.csv",
                "reason": "no_hash_compatible_candidate_found",
                "next_action": "external_acquisition_or_manual_file",
            }
        ],
        ["blocker_type", "source_system", "expected_input", "reason", "next_action"],
    )

    source_file = tmp_path / "data" / "manual_import_dropzone" / "deliveries" / "pr_doe_master.csv"
    source_file.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "award_id": "DOE-1",
            "recipient_name": "Utility",
            "recipient_name_normalized": "UTILITY",
            "recipient_uei": "",
            "awarding_agency": "DOE",
            "awarding_sub_agency": "",
            "obligated_amount": "1000",
            "award_date": "2024-01-10",
            "fiscal_year": "2024",
            "pop_state": "PR",
            "pop_county": "San Juan",
            "description": "grid modernization",
            "source_file": "pr_doe_master.csv",
            "source_dataset": "doe",
            "award_category": "grant",
            "source_system": "federal_sectoral_doe",
            "source_record_id": "doe:1",
            "source_lineage_path": "data/manual_import_dropzone/deliveries/pr_doe_master.csv",
            "source_lineage_mode": "manual",
        }
    ]
    _write_csv(
        source_file,
        rows,
        [
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
        ],
    )
    manifest_sha = _sha256(source_file)
    if not include_delivered_file:
        source_file.unlink()

    manifest_row = {
        "source_system": "federal_sectoral_doe",
        "source_file": "data/manual_import_dropzone/deliveries/pr_doe_master.csv",
        "target_output_path": "data/staging/processed/pr_doe_master.csv",
        "row_count": "1",
        "sha256": manifest_sha,
        "generated_at": "2026-05-09T00:00:00Z",
        "producer_script": "scripts/download_doe.py",
        "validation_status": "validated",
        "known_gaps": "",
        "schema_version": "r4_8d_schema_v1",
        "manifest_type": "validated_source_manifest",
        "manifest_path": "data/manifests/r4_8d/12_pr_doe_master.manifest.json",
    }
    _write_csv(
        tmp_path / "data" / "exports" / "validated_source_manifest_inventory_r4_8i.csv",
        [manifest_row],
        list(manifest_row.keys()),
    )

    _write_json(
        tmp_path / "data" / "exports" / "external_acquisition_blocker_package_r4_8i.json",
        {"external_blocker_count": 2, "blockers": [{"blocker_type": "manual_file_required"}]},
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8i.csv",
        [
            {
                "priority": "1",
                "source_family": "usaspending_backbone",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "target_dropzone_path": "data/manual_import_dropzone/r4_8e/usaspending/pr_contracts_master.csv",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
                "required_columns": "contract_id|vendor_name",
                "validation_command": "echo validate",
                "source_url_or_portal": "https://api.usaspending.gov",
                "producer_script": "",
                "manual_file_received": "False",
                "review_status": "pending_manual_file",
                "failure_reason": "no_file_present",
            }
        ],
        [
            "priority",
            "source_family",
            "expected_input",
            "target_dropzone_path",
            "target_output_path",
            "accepted_filename_patterns",
            "required_columns",
            "validation_command",
            "source_url_or_portal",
            "producer_script",
            "manual_file_received",
            "review_status",
            "failure_reason",
        ],
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
        },
    )


def test_source_delivery_gate_passes_with_absent_files_queued(tmp_path: Path):
    _bootstrap_r49c(tmp_path, include_delivered_file=False)

    status = run_external_source_delivery_gate(tmp_path)

    assert status["r4_9c_gate_passed"] is True
    assert status["r4_9c_delivery_requests_checked"] == 2
    assert status["r4_9c_files_found"] == 0
    assert status["r4_9c_files_validated"] == 0
    assert status["r4_9c_files_materialized"] == 0
    assert status["r4_9c_validated_source_manifests_total"] == 1
    assert status["r4_9c_new_validated_source_manifests"] == 0
    assert status["r4_9c_rows_available_total"] == 1
    assert status["r4_9c_new_rows_available"] == 0
    assert status["r4_9c_manual_files_still_required"] == 1
    assert status["r4_9c_physical_validated_files_still_missing"] == 1
    assert status["r4_9c_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True


def test_source_delivery_gate_materializes_delivered_validated_file(tmp_path: Path):
    _bootstrap_r49c(tmp_path, include_delivered_file=True)

    status = run_external_source_delivery_gate(tmp_path)

    assert status["r4_9c_gate_passed"] is True
    assert status["r4_9c_delivery_requests_checked"] == 2
    assert status["r4_9c_files_found"] >= 1
    assert status["r4_9c_files_validated"] >= 1
    assert status["r4_9c_files_materialized"] >= 1
    assert status["r4_9c_new_validated_source_manifests"] >= 1
    assert status["r4_9c_new_rows_available"] >= 1
    assert status["r4_9c_forbidden_artifact_usage"] is False
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    target = tmp_path / "data" / "staging" / "processed" / "pr_doe_master.csv"
    assert target.exists()
