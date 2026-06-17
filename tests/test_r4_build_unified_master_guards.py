"""R4 tests for fail-closed input guards and source lineage in build_unified_master."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts import build_unified_master as bum


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_r4_lineage_fields_are_written(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(bum, "NEW_MASTERS", [])
    monkeypatch.setattr(bum, "EXPANSION_FILES", [])

    contracts = tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    _write_csv(
        contracts,
        [
            {
                "contract_id": "A-100",
                "vendor_name": "Acme LLC",
                "agency_name": "DOE",
                "award_date": "2024-10-01",
                "obligated_amount": "100",
                "pop_state": "PR",
                "fiscal_year": "2025",
                "source_file": "normalized_expansion_demo.csv",
            },
            {
                "contract_id": "A-101",
                "vendor_name": "Beta Inc",
                "agency_name": "HUD",
                "award_date": "2024-07-01",
                "obligated_amount": "200",
                "pop_state": "PR",
                "fiscal_year": "2024",
                "source_file": "normalized_expansion_demo.csv",
            },
        ],
        fieldnames=[
            "contract_id",
            "vendor_name",
            "agency_name",
            "award_date",
            "obligated_amount",
            "pop_state",
            "fiscal_year",
            "source_file",
        ],
    )

    result = bum.run(
        root=tmp_path,
        input_map={
            "data/staging/processed/pr_contracts_master.csv": {
                "mapped_rel": "data/staging/processed/pr_contracts_master.csv",
                "mapping_mode": "exact",
            }
        },
        require_all_inputs=True,
        fail_on_forbidden=True,
    )

    output = tmp_path / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    assert output.exists()

    with output.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    assert "source_record_id" in rows[0]
    assert "source_system" in rows[0]
    assert "source_lineage_path" in rows[0]
    assert "source_lineage_mode" in rows[0]
    assert rows[0]["source_lineage_mode"] == "exact"
    assert result["source_lineage_coverage"] == 1.0
    assert result["unique_normalized_entities"] >= 1


def test_r4_missing_required_inputs_fail_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(bum, "NEW_MASTERS", [])
    monkeypatch.setattr(bum, "EXPANSION_FILES", [])

    with pytest.raises(RuntimeError, match="missing required inputs"):
        bum.run(root=tmp_path, require_all_inputs=True, fail_on_forbidden=True)


def test_r4_optional_master_absence_does_not_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    # A master whose producer has been archived (OPTIONAL_MASTERS, e.g.
    # pr_hud_master.csv) may be absent WITHOUT tripping the fail-closed guard,
    # as long as the genuinely-required inputs are present.
    monkeypatch.setattr(bum, "NEW_MASTERS", [("pr_optional_demo.csv", "demo")])
    monkeypatch.setattr(bum, "OPTIONAL_MASTERS", frozenset({"pr_optional_demo.csv"}))
    monkeypatch.setattr(bum, "EXPANSION_FILES", [])

    contracts = tmp_path / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    _write_csv(
        contracts,
        [
            {
                "contract_id": "A-1",
                "vendor_name": "Acme LLC",
                "agency_name": "DOE",
                "award_date": "2024-10-01",
                "obligated_amount": "100",
                "pop_state": "PR",
                "fiscal_year": "2025",
                "source_file": "normalized_expansion_demo.csv",
            }
        ],
        fieldnames=[
            "contract_id",
            "vendor_name",
            "agency_name",
            "award_date",
            "obligated_amount",
            "pop_state",
            "fiscal_year",
            "source_file",
        ],
    )

    # pr_optional_demo.csv is intentionally absent — the guard must NOT raise.
    result = bum.run(
        root=tmp_path,
        input_map={
            "data/staging/processed/pr_contracts_master.csv": {
                "mapped_rel": "data/staging/processed/pr_contracts_master.csv",
                "mapping_mode": "exact",
            }
        },
        require_all_inputs=True,
        fail_on_forbidden=True,
    )

    output = tmp_path / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    assert output.exists()
    assert result["unique_normalized_entities"] >= 1


def test_r4_forbidden_input_mapping_rejected(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(bum, "NEW_MASTERS", [])
    monkeypatch.setattr(bum, "EXPANSION_FILES", [])

    summary_like = tmp_path / "data" / "staging" / "processed" / "pr_contracts_summary.csv"
    _write_csv(
        summary_like,
        [
            {
                "contract_id": "S-1",
                "vendor_name": "Summary Vendor",
                "agency_name": "DOE",
                "award_date": "2024-01-01",
                "obligated_amount": "1",
                "pop_state": "PR",
                "fiscal_year": "2024",
                "source_file": "summary.csv",
            }
        ],
        fieldnames=[
            "contract_id",
            "vendor_name",
            "agency_name",
            "award_date",
            "obligated_amount",
            "pop_state",
            "fiscal_year",
            "source_file",
        ],
    )

    with pytest.raises(RuntimeError, match="forbidden artifact inputs"):
        bum.run(
            root=tmp_path,
            input_map={
                "data/staging/processed/pr_contracts_master.csv": {
                    "mapped_rel": "data/staging/processed/pr_contracts_summary.csv",
                    "mapping_mode": "fallback",
                }
            },
            require_all_inputs=True,
            fail_on_forbidden=True,
        )
