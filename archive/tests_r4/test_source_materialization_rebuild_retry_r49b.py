"""Tests for R4.9B source materialization and partial rebuild retry."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from contract_sweeper.pipeline.partial_rebuild_retry import run_partial_rebuild_retry
from contract_sweeper.pipeline.source_materialization import run_source_materialization

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


def _bootstrap_r49b(tmp_path: Path, *, include_materializable_file: bool) -> None:
    _write_json(
        tmp_path / "data" / "exports" / "final_source_recovery_status_r4_8i.json",
        {
            "r4_8i_gate_passed": True,
            "r4_8i_rows_ingested_total": 3135,
            "r4_8i_production_inputs_staged_total": 7,
            "r4_8i_validated_source_manifests_total": 7,
            "r4_8i_external_blocker_count": 25,
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
    _write_json(
        tmp_path / "data" / "exports" / "external_acquisition_blocker_package_r4_8i.json",
        {"external_blocker_count": 25, "blockers": [{"blocker_type": "manual_file_required"}]},
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
        },
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "manual_files_still_required_r4_8i.csv",
        [
            {
                "priority": "1",
                "source_family": "contracts",
                "expected_input": "data/staging/processed/pr_contracts_master.csv",
                "target_output_path": "data/staging/processed/pr_contracts_master.csv",
                "failure_reason": "no_file_present",
                "review_status": "pending_manual_file",
            }
        ],
        ["priority", "source_family", "expected_input", "target_output_path", "failure_reason", "review_status"],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "endpoints_still_blocked_r4_8i.csv",
        [
            {
                "priority": "2",
                "source_family": "grants",
                "expected_input": "data/staging/processed/pr_grants_master.csv",
                "failure_reason": "timeout",
                "retry_status": "failed_command",
                "review_status": "pending_retry",
            }
        ],
        ["priority", "source_family", "expected_input", "failure_reason", "retry_status", "review_status"],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "producers_still_blocked_r4_8i.csv",
        [
            {
                "priority": "3",
                "source_family": "subawards",
                "expected_input": "data/staging/processed/pr_subawards_master.csv",
                "failure_reason": "upstream failure",
                "retry_status": "failed_command",
                "review_status": "pending_retry",
            }
        ],
        ["priority", "source_family", "expected_input", "failure_reason", "retry_status", "review_status"],
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

    source_file_rel = "data/staging/processed/source_candidates/pr_doe_master.csv"
    target_rel = "data/staging/processed/pr_doe_master.csv"
    source_file_abs = tmp_path / source_file_rel

    sha = "b" * 64
    if include_materializable_file:
        _write_csv(
            source_file_abs,
            [
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
                    "source_lineage_path": source_file_rel,
                    "source_lineage_mode": "r4_8i_validated",
                }
            ],
            CANONICAL_COLUMNS,
        )
        sha = _sha256(source_file_abs)

    manifest_row = {
        "source_system": "federal_sectoral_doe",
        "source_file": source_file_rel,
        "target_output_path": target_rel,
        "row_count": "1",
        "sha256": sha,
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


def test_r49b_materializes_and_retries_partial_rebuild(tmp_path: Path):
    _bootstrap_r49b(tmp_path, include_materializable_file=True)

    materialization = run_source_materialization(tmp_path)
    status = run_partial_rebuild_retry(tmp_path, materialization)

    assert materialization["r4_9b_manifest_records_checked"] == 1
    assert materialization["r4_9b_files_materialized"] == 1
    assert materialization["r4_9b_files_hash_validated"] == 1
    assert materialization["r4_9b_materialization_blockers"] == 0
    assert materialization["r4_9b_forbidden_artifact_usage"] is False

    assert status["r4_9b_gate_passed"] is True
    assert status["r4_9b_rebuild_attempted"] is True
    assert status["r4_9b_rebuild_succeeded"] is True
    assert status["r4_9b_output_rows"] >= 1
    assert status["r4_9b_output_status"] == "PARTIAL_DIAGNOSTIC"
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True
    assert status["r4_9b_forbidden_artifact_usage"] is False

    target = tmp_path / "data" / "staging" / "processed" / "pr_doe_master.csv"
    assert target.exists()


def test_r49b_blocks_when_materialization_unavailable(tmp_path: Path):
    _bootstrap_r49b(tmp_path, include_materializable_file=False)

    materialization = run_source_materialization(tmp_path)
    status = run_partial_rebuild_retry(tmp_path, materialization)

    assert materialization["r4_9b_manifest_records_checked"] == 1
    assert materialization["r4_9b_files_materialized"] == 0
    assert materialization["r4_9b_files_hash_validated"] == 0
    assert materialization["r4_9b_materialization_blockers"] == 1

    assert status["r4_9b_gate_passed"] is True
    assert status["r4_9b_rebuild_attempted"] is False
    assert status["r4_9b_rebuild_succeeded"] is False
    assert status["r4_9b_output_rows"] == 0
    assert status["r4_9b_output_status"] == "BLOCKED_DIAGNOSTIC"
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True
