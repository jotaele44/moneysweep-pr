"""Tests for R4.9G scoped unfreeze and partial diagnostic rebuild."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from contract_sweeper.pipeline.scoped_partial_rebuild import run_scoped_partial_rebuild
from contract_sweeper.pipeline.scoped_unfreeze_materialization import (
    run_scoped_unfreeze_materialization,
)

CONTRACT_COLUMNS = [
    "contract_id",
    "vendor_name",
    "agency_name",
    "award_date",
    "obligated_amount",
    "pop_state",
    "source_file",
    "fiscal_year",
]

EXPANSION_COLUMNS = [
    "Award ID",
    "Recipient Name",
    "Awarding Agency",
    "Awarding Sub Agency",
    "Total Obligation",
    "Start Date",
    "Place of Performance State Code",
    "Place of Performance City",
    "Description",
    "generated_internal_id",
]

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
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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


def _csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _base_checklist_rows() -> list[dict]:
    return [
        {
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": (
                "data/manual_import_dropzone/r4_8e/usaspending/"
                "pr_contracts_master.csv"
            ),
            "target_output_path": "data/staging/processed/pr_contracts_master.csv",
            "accepted_filename_patterns": "pr_contracts_master.csv|*.csv",
            "required_columns": "|".join(CONTRACT_COLUMNS),
            "validation_command": "echo validate contracts",
            "unfreeze_condition": "deliver contracts file and validate",
            "reason_blocked": "file_not_delivered",
        },
        {
            "expected_input": "data/staging/expansion/expansion_idv_indirect_pr.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": (
                "data/manual_import_dropzone/r4_8e/usaspending/"
                "expansion_idv_indirect_pr.csv"
            ),
            "target_output_path": "data/staging/expansion/expansion_idv_indirect_pr.csv",
            "accepted_filename_patterns": "expansion_idv_indirect_pr.csv|*.csv",
            "required_columns": "|".join(EXPANSION_COLUMNS),
            "validation_command": "echo validate expansion",
            "unfreeze_condition": "deliver expansion file and validate",
            "reason_blocked": "file_not_delivered",
        },
        {
            "expected_input": "data/staging/processed/pr_grants_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "blocker_class": "manual_file_required",
            "target_dropzone_path": (
                "data/manual_import_dropzone/r4_8e/usaspending/"
                "pr_grants_master.csv"
            ),
            "target_output_path": "data/staging/processed/pr_grants_master.csv",
            "accepted_filename_patterns": "pr_grants_master.csv|*.csv",
            "required_columns": "|".join(CANONICAL_COLUMNS),
            "validation_command": "echo validate grants",
            "unfreeze_condition": "deliver grants file and validate",
            "reason_blocked": "file_not_delivered",
        },
    ]


def _bootstrap(tmp_path: Path, *, bad_hash: bool = False) -> None:
    contracts_path = tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    expansion_path = tmp_path / "data" / "staging" / "expansion" / "expansion_idv_indirect_pr.csv"
    grants_path = tmp_path / "data" / "staging" / "processed" / "pr_grants_master.csv"

    _write_csv(
        contracts_path,
        [
            {
                "contract_id": "CONT-1",
                "vendor_name": "Puerto Rico Contractor LLC",
                "agency_name": "GSA",
                "award_date": "2024-01-15",
                "obligated_amount": "1000",
                "pop_state": "PR",
                "source_file": "pr_contracts_master.csv",
                "fiscal_year": "2024",
            }
        ],
        CONTRACT_COLUMNS,
    )
    _write_csv(
        expansion_path,
        [
            {
                "Award ID": "EXP-1",
                "Recipient Name": "Expansion Vendor Inc",
                "Awarding Agency": "DOD",
                "Awarding Sub Agency": "ARMY",
                "Total Obligation": "2000",
                "Start Date": "2024-03-10",
                "Place of Performance State Code": "PR",
                "Place of Performance City": "Ponce",
                "Description": "scoped expansion",
                "generated_internal_id": "GEN-1",
            }
        ],
        EXPANSION_COLUMNS,
    )
    _write_csv(
        grants_path,
        [
            {
                "award_id": "GRANT-1",
                "recipient_name": "Should Not Be Used",
                "recipient_name_normalized": "SHOULD NOT BE USED",
                "recipient_uei": "",
                "awarding_agency": "HHS",
                "awarding_sub_agency": "",
                "obligated_amount": "9999",
                "award_date": "2024-01-01",
                "fiscal_year": "2024",
                "pop_state": "PR",
                "pop_county": "",
                "description": "non-candidate row",
                "source_file": "pr_grants_master.csv",
                "source_dataset": "grants",
                "award_category": "grant",
                "source_system": "grants",
                "source_record_id": "grants:GRANT-1",
                "source_lineage_path": "data/staging/processed/pr_grants_master.csv",
                "source_lineage_mode": "non_candidate",
            }
        ],
        CANONICAL_COLUMNS,
    )

    checklist_rows = _base_checklist_rows()
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv",
        checklist_rows,
        list(checklist_rows[0].keys()),
    )
    _write_json(
        tmp_path / "data" / "exports" / "source_delivery_watch_status_r4_9f.json",
        {
            "r4_9f_gate_passed": True,
            "r4_9f_unfreeze_candidates": 1 if bad_hash else 2,
            "r4_9f_sources_still_missing": 1,
            "r4_9f_downloads_executed": False,
            "r4_9f_rows_ingested": 0,
            "r4_9f_production_inputs_staged": 0,
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "phase_7_8_blocked": True,
        },
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {
            "production_status": "NON_PRODUCTION_DIAGNOSTIC",
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
        },
    )

    candidate_rows = [
        {
            "expected_input": "data/staging/processed/pr_contracts_master.csv",
            "source_family": "usaspending_federal_awards_backbone",
            "blocker_class": "manual_file_required",
            "candidate_path": str(contracts_path),
            "candidate_relpath": "data/staging/processed/pr_contracts_master.csv",
            "candidate_filename": "pr_contracts_master.csv",
            "candidate_row_count": "1",
            "candidate_sha256": "0" * 64 if bad_hash else _sha256(contracts_path),
            "validation_command": "echo validate contracts",
            "unfreeze_condition": "deliver contracts file and validate",
        }
    ]
    if not bad_hash:
        candidate_rows.append(
            {
                "expected_input": "data/staging/expansion/expansion_idv_indirect_pr.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "blocker_class": "manual_file_required",
                "candidate_path": str(expansion_path),
                "candidate_relpath": "data/staging/expansion/expansion_idv_indirect_pr.csv",
                "candidate_filename": "expansion_idv_indirect_pr.csv",
                "candidate_row_count": "1",
                "candidate_sha256": _sha256(expansion_path),
                "validation_command": "echo validate expansion",
                "unfreeze_condition": "deliver expansion file and validate",
            }
        )
    _write_csv(
        tmp_path / "data" / "review_queue" / "unfreeze_candidates_r4_9f.csv",
        candidate_rows,
        list(candidate_rows[0].keys()),
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_still_missing_r4_9f.csv",
        [
            {
                "expected_input": "data/staging/processed/pr_grants_master.csv",
                "source_family": "usaspending_federal_awards_backbone",
                "blocker_class": "manual_file_required",
                "target_dropzone_path": (
                    "data/manual_import_dropzone/r4_8e/usaspending/"
                    "pr_grants_master.csv"
                ),
                "target_output_path": "data/staging/processed/pr_grants_master.csv",
                "missing_reason": "not_in_unfreeze_candidates",
                "next_action": "await_valid_source_delivery",
                "validation_command": "echo validate grants",
                "unfreeze_condition": "deliver grants file and validate",
            }
        ],
        [
            "expected_input",
            "source_family",
            "blocker_class",
            "target_dropzone_path",
            "target_output_path",
            "missing_reason",
            "next_action",
            "validation_command",
            "unfreeze_condition",
        ],
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "downstream_phase_blockers_r4_9f.csv",
        [
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R5_ENTITY_RESOLUTION",
                "blocked": "True",
                "blocker_reason": "R5 remains blocked",
                "unfreeze_condition": "restore physical source coverage",
                "status": "blocked",
            },
            {
                "generated_at": "2026-05-09T00:00:00Z",
                "phase_code": "R8_GRAPH_REBUILD",
                "blocked": "True",
                "blocker_reason": "R8 remains blocked",
                "unfreeze_condition": "restore physical source coverage",
                "status": "blocked",
            },
        ],
        ["generated_at", "phase_code", "blocked", "blocker_reason", "unfreeze_condition", "status"],
    )


def test_r49g_validates_only_unfreeze_candidates_and_rebuilds_partial(tmp_path: Path):
    _bootstrap(tmp_path)

    materialization = run_scoped_unfreeze_materialization(tmp_path)
    status = run_scoped_partial_rebuild(tmp_path, materialization)

    assert status["r4_9g_gate_passed"] is True
    assert status["r4_9g_candidates_loaded"] == 2
    assert status["r4_9g_candidates_validated"] == 2
    assert status["r4_9g_candidates_rejected"] == 0
    assert status["r4_9g_sources_still_blocked"] == 1
    assert status["r4_9g_partial_rebuild_attempted"] is True
    assert status["r4_9g_partial_rebuild_succeeded"] is True
    assert status["r4_9g_partial_rebuild_rows"] == 2
    assert status["r4_9g_unique_entities"] == 2
    assert status["r4_9g_source_lineage_coverage"] == 1.0
    assert status["r4_9g_output_status"] == "PARTIAL_DIAGNOSTIC"
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["r4_9g_downloads_executed"] is False
    assert status["r4_9g_endpoint_retries_executed"] is False
    assert status["r4_9g_production_inputs_staged"] == 0
    assert status["r4_9g_forbidden_artifact_usage"] is False
    assert status["phase_7_8_blocked"] is True
    assert status["downstream_phases_blocked"] is True

    output = (
        tmp_path
        / "data"
        / "staging"
        / "processed"
        / "partial"
        / "contracts_master_partial_diagnostic_r4_9g.csv"
    )
    df = pd.read_csv(output, dtype=str, low_memory=False)
    assert set(df["diagnostic_status"]) == {"PARTIAL_DIAGNOSTIC"}
    assert "GRANT-1" not in set(df["award_id"])
    assert not (tmp_path / "data" / "staging" / "processed" / "pr_all_awards_master.csv").exists()

    manifests = sorted((tmp_path / "data" / "manifests" / "r4_9g").glob("*.json"))
    assert len(manifests) == 2


def test_r49g_blocks_rebuild_when_candidate_validation_fails(tmp_path: Path):
    _bootstrap(tmp_path, bad_hash=True)

    materialization = run_scoped_unfreeze_materialization(tmp_path)
    status = run_scoped_partial_rebuild(tmp_path, materialization)

    assert status["r4_9g_gate_passed"] is True
    assert status["r4_9g_candidates_loaded"] == 1
    assert status["r4_9g_candidates_validated"] == 0
    assert status["r4_9g_candidates_rejected"] == 1
    assert status["r4_9g_sources_still_blocked"] == 2
    assert status["r4_9g_partial_rebuild_attempted"] is False
    assert status["r4_9g_partial_rebuild_succeeded"] is False
    assert status["r4_9g_partial_rebuild_rows"] == 0
    assert status["r4_9g_output_status"] == "BLOCKED_DIAGNOSTIC"
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    report_rows = _csv_rows(
        tmp_path / "data" / "exports" / "scoped_unfreeze_validation_report_r4_9g.csv"
    )
    assert report_rows[0]["validation_reason"] == "candidate_hash_mismatch"
    assert not (tmp_path / "data" / "manifests" / "r4_9g").exists()
