"""Tests for R3 source coverage and master-input audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from contract_sweeper.validation.source_coverage import SourceSpec, run_audit


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_r3_audit_detects_master_input_gap_and_blocks_phase_7_8(tmp_path: Path):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "build_unified_master.py").write_text(
        "NEW_MASTERS = [('pr_all_awards_master.csv', 'all_awards')]\n"
        "EXPANSION_FILES = ['pr_emma_bonds.csv']\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "deduplicate_master.py").write_text("print('ok')\n", encoding="utf-8")

    _write_json(
        tmp_path / "data" / "reports" / "pr_report_summary.json",
        {
            "awards": {"unique_entities": 18},
            "power_network": {"total_ranked": 18, "bond_actors_count": 0},
        },
    )
    _write_json(
        tmp_path / "data" / "staging" / "processed" / "dominance_summary.json",
        {"total_rows": 4503, "unique_vendors": 18},
    )
    _write_json(
        tmp_path / "data" / "staging" / "processed" / "pr_all_awards_summary.json",
        {"total_rows": 4503, "unique_recipients": 18},
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {"phase_7_8_blocked": True, "r2_gate_passed": False},
    )

    result = run_audit(tmp_path)

    assert result["r3_gate_passed"] is False
    assert result["phase_7_8_blocked"] is True
    assert (
        result["r3_primary_collapse_cause"]
        == "build_unified_master_input_gap_with_stale_summary_replay"
    )

    assert (tmp_path / "data" / "exports" / "source_coverage_audit.csv").exists()
    assert (tmp_path / "data" / "exports" / "source_field_completeness.csv").exists()
    assert (tmp_path / "data" / "review_queue" / "source_backfill_queue.csv").exists()


def test_r3_audit_can_pass_with_full_coverage_for_custom_single_source(tmp_path: Path, monkeypatch):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "build_unified_master.py").write_text(
        "NEW_MASTERS = [('pr_all_awards_master.csv', 'all_awards')]\n"
        "EXPANSION_FILES = ['pr_emma_bonds.csv']\n",
        encoding="utf-8",
    )
    (tmp_path / "scripts" / "deduplicate_master.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "scripts" / "single_source_fetch.py").write_text(
        "endpoint='https://example.test'\nnext_page = 1\n",
        encoding="utf-8",
    )

    # Builder inputs present.
    _write_csv(
        tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv",
        [{"award_id": "A1", "recipient_name": "Acme", "obligated_amount": "10", "year": "2024"}],
        fieldnames=["award_id", "recipient_name", "obligated_amount", "year"],
    )
    _write_csv(
        tmp_path / "data" / "staging" / "processed" / "pr_all_awards_master.csv",
        [{"award_id": "A2", "recipient_name": "Beta", "obligated_amount": "20", "year": "2024"}],
        fieldnames=["award_id", "recipient_name", "obligated_amount", "year"],
    )
    _write_csv(
        tmp_path / "data" / "staging" / "expansion" / "pr_emma_bonds.csv",
        [{"award_id": "B1", "recipient_name": "Gamma", "obligated_amount": "30", "year": "2024"}],
        fieldnames=["award_id", "recipient_name", "obligated_amount", "year"],
    )

    # Single source with full year coverage and manifest metadata.
    source_csv = tmp_path / "data" / "staging" / "processed" / "single_source_2024.csv"
    _write_csv(
        source_csv,
        [{"award_id": "Z1", "recipient_name": "Delta", "obligated_amount": "100", "year": "2024"}],
        fieldnames=["award_id", "recipient_name", "obligated_amount", "year"],
    )
    _write_json(
        source_csv.with_suffix(source_csv.suffix + ".manifest.json"),
        {"source": "single_source", "rows": 1},
    )

    _write_json(
        tmp_path / "data" / "reports" / "pr_report_summary.json",
        {"awards": {"unique_entities": 150}},
    )
    _write_json(
        tmp_path / "data" / "staging" / "processed" / "dominance_summary.json",
        {"total_rows": 1000, "unique_vendors": 150},
    )
    _write_json(
        tmp_path / "data" / "staging" / "processed" / "pr_all_awards_summary.json",
        {"total_rows": 1000, "unique_recipients": 150},
    )
    _write_json(
        tmp_path / "data" / "exports" / "rebuild_status.json",
        {"phase_7_8_blocked": False, "r2_gate_passed": True},
    )

    monkeypatch.setattr(
        "contract_sweeper.validation.source_coverage.SOURCE_SPECS",
        (
            SourceSpec(
                source_system="single_source",
                script_path="scripts/single_source_fetch.py",
                file_patterns=("data/staging/processed/single_source_2024.csv",),
                years_expected=(2024,),
                requires_pagination=True,
                endpoint_hint="https://example.test",
            ),
        ),
    )

    result = run_audit(tmp_path)
    assert result["r3_gate_passed"] is True
    assert result["phase_7_8_blocked"] is False
    assert result["r3_primary_collapse_cause"] == "source_or_builder_cause_not_determined"


def test_source_coverage_csv_has_required_columns(tmp_path: Path):
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "build_unified_master.py").write_text(
        "NEW_MASTERS = []\nEXPANSION_FILES = []\n", encoding="utf-8"
    )
    (tmp_path / "scripts" / "deduplicate_master.py").write_text("print('ok')\n", encoding="utf-8")
    _write_json(tmp_path / "data" / "exports" / "rebuild_status.json", {})

    run_audit(tmp_path)

    rows = list(
        csv.DictReader(
            (tmp_path / "data" / "exports" / "source_coverage_audit.csv").open(
                "r", encoding="utf-8"
            )
        )
    )
    assert rows

    required = {
        "source_system",
        "years_expected",
        "years_present",
        "year_coverage_pct",
        "rows_total",
        "rows_by_year",
        "field_completeness_pct",
        "pagination_complete",
        "capped_result_detected",
        "fixture_detected",
        "download_timestamp",
        "source_url_or_endpoint",
        "cache_source",
        "backfill_required",
    }
    assert required.issubset(rows[0].keys())
