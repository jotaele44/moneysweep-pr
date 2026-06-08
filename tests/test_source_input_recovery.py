"""Tests for R4.5 source input recovery and canonical staging."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.validation.source_input_recovery import run_recovery


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_builder_script(path: Path, new_masters: str, expansion_files: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"NEW_MASTERS = {new_masters}\nEXPANSION_FILES = {expansion_files}\n",
        encoding="utf-8",
    )


def test_r45_rejects_summary_artifacts_and_writes_manual_queue(tmp_path: Path):
    _write_builder_script(
        tmp_path / "scripts" / "build_unified_master.py",
        "[('pr_grants_master.csv', 'grants')]",
        "[]",
    )
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})

    # This candidate is intentionally rejected by summary token.
    _write_csv(
        tmp_path / "data" / "exports" / "pr_grants_summary.csv",
        [{"award_id": "A1", "recipient_name": "Acme", "obligated_amount": "100"}],
        ["award_id", "recipient_name", "obligated_amount"],
    )

    result = run_recovery(tmp_path)

    assert result["expected_input_count"] == 2  # contracts core + grants master
    assert result["recovered_input_count"] == 0
    assert result["manual_queue_count"] == 2
    assert result["rejected_artifact_candidate_count"] >= 1
    assert result["phase_7_8_blocked"] is True

    assert (tmp_path / "data" / "review_queue" / "manual_source_download_queue.csv").exists()


def test_r45_recovers_contract_and_canonical_staging_with_lineage(tmp_path: Path):
    _write_builder_script(
        tmp_path / "scripts" / "build_unified_master.py",
        "[('pr_grants_master.csv', 'grants')]",
        "[]",
    )
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})

    _write_csv(
        tmp_path / "data" / "raw" / "contracts_seed.csv",
        [
            {
                "contract_id": "C-1",
                "vendor_name": "Acme LLC",
                "agency_name": "DOE",
                "award_date": "2024-10-01",
                "obligated_amount": "100",
                "fiscal_year": "2025",
                "pop_state": "PR",
            }
        ],
        [
            "contract_id",
            "vendor_name",
            "agency_name",
            "award_date",
            "obligated_amount",
            "fiscal_year",
            "pop_state",
        ],
    )
    _write_csv(
        tmp_path / "data" / "raw" / "pr_grants_seed.csv",
        [
            {
                "award_id": "G-1",
                "recipient_name": "Beta Inc",
                "awarding_agency": "HUD",
                "obligated_amount": "250",
                "award_date": "2024-07-15",
                "fiscal_year": "2024",
                "pop_state": "PR",
            }
        ],
        [
            "award_id",
            "recipient_name",
            "awarding_agency",
            "obligated_amount",
            "award_date",
            "fiscal_year",
            "pop_state",
        ],
    )

    result = run_recovery(tmp_path)
    assert result["recovered_input_count"] == 2
    assert result["manual_queue_count"] == 0
    assert result["r4_5_gate_passed"] is True

    contracts_out = tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    grants_out = tmp_path / "data" / "staging" / "processed" / "pr_grants_master.csv"
    assert contracts_out.exists()
    assert grants_out.exists()

    with contracts_out.open("r", encoding="utf-8", newline="") as handle:
        contracts_rows = list(csv.DictReader(handle))
    with grants_out.open("r", encoding="utf-8", newline="") as handle:
        grants_rows = list(csv.DictReader(handle))

    assert contracts_rows[0]["source_lineage_mode"] == "recovered"
    assert contracts_rows[0]["source_record_id"].startswith("contracts:")
    assert grants_rows[0]["source_lineage_mode"] == "recovered"
    assert grants_rows[0]["source_record_id"].startswith("grants:")
    assert "recipient_name_normalized" in grants_rows[0]


def test_r45_outputs_required_status_files(tmp_path: Path):
    _write_builder_script(
        tmp_path / "scripts" / "build_unified_master.py",
        "[]",
        "[]",
    )
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})

    run_recovery(tmp_path)

    assert (tmp_path / "data" / "exports" / "source_input_recovery_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "source_input_recovery_status.json").exists()
    assert (tmp_path / "data" / "review_queue" / "manual_source_download_queue.csv").exists()
    status = json.loads(
        (tmp_path / "data" / "exports" / "source_input_recovery_status.json").read_text()
    )
    assert "phase_7_8_blocked" in status
    assert status["phase_7_8_blocked"] is True
