"""Tests for the Tranche B source-intake controller."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.source_intake_helpers import read_csv_rows
from scripts.source_intake_tranche_b import (
    CONTRACTOR_REFERENCE_COLUMNS,
    INFRASTRUCTURE_FACT_COLUMNS,
    INFRASTRUCTURE_PROJECT_COLUMNS,
    LOBBYING_COLUMNS,
    LOCAL_CONTRACT_COLUMNS,
    SOURCE_SPECS,
    run,
)


@pytest.mark.unit
def test_source_specs_cover_tranche_b_scope():
    assert set(SOURCE_SPECS) == {
        "act",
        "acuden",
        "prasa_projects",
        "prasa_cer",
        "cabilderos",
        "lda",
        "dcaa",
    }


@pytest.mark.unit
def test_declared_columns_include_provenance_fields():
    for columns in (
        LOCAL_CONTRACT_COLUMNS,
        INFRASTRUCTURE_PROJECT_COLUMNS,
        INFRASTRUCTURE_FACT_COLUMNS,
        LOBBYING_COLUMNS,
        CONTRACTOR_REFERENCE_COLUMNS,
    ):
        assert "source_id" in columns
        assert "source_file" in columns
        assert "evidence_tier" in columns
        assert "confidence" in columns
        assert "raw_text_excerpt" in columns


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)


@pytest.mark.integration
def test_run_builds_local_contract_output(tmp_path: Path):
    _write_csv(
        tmp_path / "data" / "raw" / "ACT Transition Contracts" / "act.csv",
        ["Contract ID", "Contratista", "Agencia", "Monto", "Status"],
        [["ACT-1", "Acme LLC", "ACT", "1000", "Active"]],
    )
    summary = run(root=tmp_path, sources=["act"], force=True)
    assert summary["status"] == "prepared"
    assert summary["rows_total"] == 1
    rows = read_csv_rows(tmp_path / "data" / "staging" / "processed" / "pr_act_transition_contracts.csv")
    assert list(rows[0].keys()) == LOCAL_CONTRACT_COLUMNS
    assert rows[0]["source_id"] == "act_transition_contracts"
    assert rows[0]["contract_id"] == "ACT-1"
    assert rows[0]["contractor_name"] == "Acme LLC"


@pytest.mark.integration
def test_run_builds_all_staging_outputs_even_without_dropzones(tmp_path: Path):
    summary = run(root=tmp_path, force=True)
    assert summary["status"] == "prepared"
    assert summary["sources_total"] == 7
    assert summary["rows_total"] == 0
    assert summary["materialization_promotion"] == "not_performed"
    report = tmp_path / "reports" / "tranche_b_source_intake_readiness.json"
    assert report.exists()
    for spec in SOURCE_SPECS.values():
        assert (tmp_path / spec.output).exists()


@pytest.mark.integration
def test_run_builds_lobby_and_reference_outputs(tmp_path: Path):
    _write_csv(
        tmp_path / "data" / "raw" / "Cabilderos" / "cabilderos.csv",
        ["Cabildero", "Cliente", "Fecha de Registro"],
        [["Lobbyist A", "Client A", "2024-01-01"]],
    )
    _write_csv(
        tmp_path / "data" / "raw" / "DCAA Active Contractors" / "vendors.csv",
        ["Name", "UEI", "CAGE", "Status"],
        [["Vendor A LLC", "UEI123", "1ABC2", "active"]],
    )
    summary = run(root=tmp_path, sources=["cabilderos", "dcaa"], force=True)
    assert summary["rows_total"] == 2

    lobby_rows = read_csv_rows(tmp_path / "data" / "staging" / "processed" / "pr_cabilderos_registry.csv")
    assert list(lobby_rows[0].keys()) == LOBBYING_COLUMNS
    assert lobby_rows[0]["registrant_name"] == "Lobbyist A"
    assert lobby_rows[0]["client_name"] == "Client A"

    vendor_rows = read_csv_rows(tmp_path / "data" / "staging" / "processed" / "dcaa_active_contractors.csv")
    assert list(vendor_rows[0].keys()) == CONTRACTOR_REFERENCE_COLUMNS
    assert vendor_rows[0]["contractor_name"] == "Vendor A LLC"
    assert vendor_rows[0]["normalized_name"] == "VENDOR A"
