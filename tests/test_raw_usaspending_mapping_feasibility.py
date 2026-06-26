"""Tests for R4.9H2 raw USAspending mapping feasibility review."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from moneysweep.pipeline.raw_usaspending_mapping_feasibility import (
    run_raw_usaspending_mapping_feasibility,
)


REJECTED_FIELDNAMES = [
    "expected_input",
    "source_family",
    "blocker_class",
    "target_output_path",
    "target_dropzone_path",
    "raw_display_path",
    "raw_container_path",
    "raw_member_path",
    "raw_extension",
    "raw_row_count",
    "raw_sha256",
    "likely_source_type",
    "required_columns",
    "raw_columns",
    "mapped_columns",
    "missing_columns",
    "mapping_profile",
    "validation_status",
    "validation_reason",
]

BLOCKED_FIELDNAMES = [
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
    "r4_9h_status",
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


def _csv_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _bootstrap_inputs(
    tmp_path: Path,
    *,
    rejected_rows: list[dict],
    blocked_rows: list[dict],
) -> None:
    _write_csv(
        tmp_path / "data" / "review_queue" / "raw_usaspending_rejected_candidates_r4_9h.csv",
        rejected_rows,
        REJECTED_FIELDNAMES,
    )
    _write_csv(
        tmp_path / "data" / "exports" / "raw_usaspending_candidate_matches_r4_9h.csv",
        [],
        REJECTED_FIELDNAMES,
    )
    _write_csv(
        tmp_path / "data" / "exports" / "raw_usaspending_validation_report_r4_9h.csv",
        [],
        REJECTED_FIELDNAMES,
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "sources_still_blocked_r4_9h.csv",
        blocked_rows,
        BLOCKED_FIELDNAMES,
    )
    _write_csv(
        tmp_path / "data" / "review_queue" / "source_delivery_checklist_r4_9e.csv",
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


def _rejected_row(
    *,
    expected_input: str,
    raw_display_path: str,
    raw_columns: str,
    mapped_columns: str,
    missing_columns: str,
) -> dict:
    return {
        "expected_input": expected_input,
        "source_family": "usaspending_federal_awards_backbone",
        "blocker_class": "manual_file_required",
        "target_output_path": expected_input,
        "target_dropzone_path": f"data/manual_import_dropzone/{Path(expected_input).name}",
        "raw_display_path": raw_display_path,
        "raw_container_path": "data/raw/USAS.zip",
        "raw_member_path": raw_display_path.split("::")[-1],
        "raw_extension": ".csv",
        "raw_row_count": "12",
        "raw_sha256": "0" * 64,
        "likely_source_type": "unknown_usaspending",
        "required_columns": mapped_columns.replace("<-deterministic_derivation", ""),
        "raw_columns": raw_columns,
        "mapped_columns": mapped_columns,
        "missing_columns": missing_columns,
        "mapping_profile": "unmappable_raw_export",
        "validation_status": "rejected",
        "validation_reason": f"raw_missing_required_or_mappable_columns:{missing_columns}",
    }


def _blocked_row(expected_input: str) -> dict:
    return {
        "generated_at": "2026-05-09T00:00:00Z",
        "expected_input": expected_input,
        "source_family": "usaspending_federal_awards_backbone",
        "blocker_class": "manual_file_required",
        "target_dropzone_path": f"data/manual_import_dropzone/{Path(expected_input).name}",
        "target_output_path": expected_input,
        "blocker_reason": "candidate_missing_required_columns",
        "next_action": "external_source_delivery_or_raw_transform_mapping_review",
        "validation_command": "echo validate",
        "unfreeze_condition": "valid source delivered",
        "r4_9h_status": "still_blocked",
    }


def test_mapping_feasibility_reviews_rejections_without_creating_unfreeze_candidates(
    tmp_path: Path,
) -> None:
    candidate_target = "data/staging/processed/pr_grants_master.csv"
    reject_target = "data/staging/processed/pr_subawards_master.csv"
    _bootstrap_inputs(
        tmp_path,
        rejected_rows=[
            _rejected_row(
                expected_input=candidate_target,
                raw_display_path="data/raw/USAS.zip::USAS/data/puerto_rico_awards.csv",
                raw_columns="award_id|recipient_name|obligated_amount|award_date|fiscal_year",
                mapped_columns="award_id<-award_id|recipient_name<-recipient_name",
                missing_columns="pop_state|source_file|source_record_id",
            ),
            _rejected_row(
                expected_input=reject_target,
                raw_display_path="data/raw/USAS.zip::USAS/data/derived/federal_spending.csv",
                raw_columns="is_pr_vendor|vendor_name|agency_name|amount_usd",
                mapped_columns="recipient_name<-vendor_name",
                missing_columns="award_date|obligated_amount|pop_state|recipient_name",
            ),
        ],
        blocked_rows=[_blocked_row(candidate_target), _blocked_row(reject_target)],
    )

    status = run_raw_usaspending_mapping_feasibility(tmp_path)

    assert status["r4_9h2_gate_passed"] is True
    assert status["rejected_candidates_reviewed"] == 2
    assert status["transform_candidates"] == 1
    assert status["transform_rejects"] == 1
    assert status["targets_potentially_unblockable"] == 1
    assert status["targets_still_external_only"] == 1
    assert status["downloads_executed"] is False
    assert status["rows_ingested"] == 0
    assert status["production_inputs_staged"] == 0
    assert status["unfreeze_candidates_created"] == 0
    assert status["production_status"] == "NON_PRODUCTION_DIAGNOSTIC"
    assert status["phase_7_8_blocked"] is True

    candidates = _csv_rows(
        tmp_path / "data" / "review_queue" / "raw_usaspending_transform_candidates_r4_9h2.csv"
    )
    rejects = _csv_rows(
        tmp_path / "data" / "review_queue" / "raw_usaspending_transform_rejects_r4_9h2.csv"
    )
    still_blocked = _csv_rows(
        tmp_path / "data" / "review_queue" / "sources_still_blocked_r4_9h2.csv"
    )

    assert candidates[0]["expected_input"] == candidate_target
    assert candidates[0]["transform_phase_allowed"] == "False"
    assert "pop_state" in candidates[0]["deterministically_derivable_columns"]
    assert rejects[0]["expected_input"] == reject_target
    assert "pop_state" in rejects[0]["cannot_infer_safely_columns"]
    assert {row["expected_input"]: row["r4_9h2_status"] for row in still_blocked} == {
        candidate_target: "potential_transform_candidate_but_still_blocked",
        reject_target: "still_external_only",
    }


def test_mapping_feasibility_keeps_is_pr_vendor_pop_state_rejected(
    tmp_path: Path,
) -> None:
    expected_input = "data/staging/processed/pr_grants_master.csv"
    _bootstrap_inputs(
        tmp_path,
        rejected_rows=[
            _rejected_row(
                expected_input=expected_input,
                raw_display_path=(
                    "data/raw/USAS.zip::USAS/data/derived/federal_spending_enriched.csv"
                ),
                raw_columns="is_pr_vendor|award_id|recipient_name|obligated_amount",
                mapped_columns="award_id<-award_id|recipient_name<-recipient_name",
                missing_columns="pop_state",
            )
        ],
        blocked_rows=[_blocked_row(expected_input)],
    )

    status = run_raw_usaspending_mapping_feasibility(tmp_path)

    assert status["r4_9h2_gate_passed"] is True
    assert status["transform_candidates"] == 0
    assert status["transform_rejects"] == 1
    assert status["targets_potentially_unblockable"] == 0
    assert status["targets_still_external_only"] == 1

    matrix = _csv_rows(
        tmp_path / "data" / "exports" / "raw_usaspending_mapping_feasibility_matrix_r4_9h2.csv"
    )
    assert matrix[0]["feasibility_status"] == "transform_reject"
    assert matrix[0]["cannot_infer_safely_columns"] == "pop_state"
    assert "is_pr_vendor exists" in matrix[0]["classification_notes"]
