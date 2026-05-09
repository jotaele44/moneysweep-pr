"""Tests for R4.9A partial diagnostic master rebuild."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from contract_sweeper.pipeline.partial_master_rebuild import run_partial_master_rebuild


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


def _bootstrap_inputs(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "final_source_recovery_status_r4_8i.json",
        {
            "r4_8i_gate_passed": True,
            "r4_8i_rows_ingested_total": 10,
            "r4_8i_production_inputs_staged_total": 1,
            "r4_8i_validated_source_manifests_total": 1,
            "r4_8i_external_blocker_count": 2,
            "r4_8i_forbidden_artifact_usage": False,
            "phase_7_8_blocked": True,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        },
    )

    _write_csv(
        tmp_path / "data" / "exports" / "final_source_recovery_results_r4_8i.csv",
        [],
        ["priority", "expected_input", "terminal_status"],
    )

    # One validated staged input (DOE) with canonical schema.
    doe_path = tmp_path / "data" / "staging" / "processed" / "pr_doe_master.csv"
    doe_rows = [
        {
            "award_id": "DOE-1",
            "recipient_name": "Example Utility",
            "recipient_name_normalized": "EXAMPLE UTILITY",
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
            "source_record_id": "doe:DOE-1",
            "source_lineage_path": "data/staging/processed/pr_doe_master.csv",
            "source_lineage_mode": "r4_8d_validated",
        }
    ]
    _write_csv(doe_path, doe_rows, CANONICAL_COLUMNS)

    manifest_row = {
        "source_system": "federal_sectoral_doe",
        "source_file": "data/staging/processed/pr_doe_master.csv",
        "target_output_path": "data/staging/processed/pr_doe_master.csv",
        "row_count": "1",
        "sha256": _sha256(doe_path),
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
        {
            "external_blocker_count": 2,
            "blockers": [
                {"blocker_type": "manual_file_required"},
                {"blocker_type": "endpoint_blocked"},
            ],
        },
    )

    manual_rows = [
        {
            "priority": "1",
            "source_family": "contracts",
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "failure_reason": "no_file_present",
            "review_status": "pending_manual_file",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8i.csv",
        manual_rows,
        list(manual_rows[0].keys()),
    )

    endpoint_rows = [
        {
            "priority": "2",
            "source_family": "grants",
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "failure_reason": "timeout",
            "retry_status": "failed_command",
            "review_status": "pending_retry",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "endpoints_still_blocked_r4_8i.csv",
        endpoint_rows,
        list(endpoint_rows[0].keys()),
    )

    producer_rows = [
        {
            "priority": "3",
            "source_family": "subawards",
            "expected_input": "data/staging/processed/pr_subawards_master.csv",
            "failure_reason": "upstream failure",
            "retry_status": "failed_command",
            "review_status": "pending_retry",
        }
    ]
    _write_csv(
        tmp_path / "data" / "review_queue" / "producers_still_blocked_r4_8i.csv",
        producer_rows,
        list(producer_rows[0].keys()),
    )

    _write_csv(
        tmp_path / "data" / "review_queue" / "backfill_retry_order_r4_8i.csv",
        [
            {
                "retry_rank": "1",
                "priority": "1",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "source_family": "contracts",
                "next_action": "require_manual_file",
                "reason": "no_file_present",
            }
        ],
        ["retry_rank", "priority", "expected_input", "source_family", "next_action", "reason"],
    )

    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )


def test_r49a_runs_and_writes_outputs(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    result = run_partial_master_rebuild(tmp_path)

    assert result["r4_9a_gate_passed"] is True
    assert result["r4_9a_validated_inputs_available"] == 1
    assert result["r4_9a_missing_inputs"] == 1
    assert result["r4_9a_external_blockers"] == 2
    assert result["r4_9a_rebuild_attempted"] is True
    assert result["r4_9a_rebuild_succeeded"] is True
    assert result["r4_9a_output_rows"] >= 1
    assert result["r4_9a_unique_entities"] >= 1
    assert result["r4_9a_source_lineage_coverage"] >= 1.0
    assert result["r4_9a_output_status"] == "PARTIAL_DIAGNOSTIC"
    assert result["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert result["r4_9a_forbidden_artifact_usage"] is False
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "exports" / "partial_master_rebuild_status_r4_9a.json").exists()
    assert (tmp_path / "data" / "exports" / "partial_master_rebuild_inputs_r4_9a.csv").exists()
    assert (tmp_path / "data" / "exports" / "partial_master_rebuild_gap_report_r4_9a.csv").exists()
    assert (tmp_path / "data" / "exports" / "partial_master_rebuild_lineage_report_r4_9a.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "partial_master_missing_inputs_r4_9a.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "partial_master_blockers_r4_9a.csv").exists()

    assert (
        tmp_path
        / "data"
        / "staging"
        / "processed"
        / "partial"
        / "contracts_master_partial_diagnostic.csv"
    ).exists()


def test_r49a_blocks_forbidden_artifact_path(tmp_path: Path):
    _bootstrap_inputs(tmp_path)

    manual_path = tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8i.csv"
    rows = list(csv.DictReader(manual_path.open(encoding="utf-8")))
    rows[0]["expected_input"] = "data/staging/processed/investigative_report.csv"
    _write_csv(manual_path, rows, list(rows[0].keys()))

    result = run_partial_master_rebuild(tmp_path)

    assert result["r4_9a_gate_passed"] is False
    assert result["r4_9a_forbidden_artifact_usage"] is True
    assert result["r4_9a_output_status"] == "BLOCKED_DIAGNOSTIC"
