"""Tests for the PR State Election Commission (CEE/CEEPUR) donations ingester
(scripts.ingest_donaciones).

Covers the pure column-mapping transform and the full drop-file -> processed-CSV
chain. The ingester reads operator-delivered CSV exports from
data/raw/Donaciones/ — no network code — so these run fully offline.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_donaciones import OUTPUT_COLUMNS, _map_col, _parse_df, run


# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_map_col_matches_spanish_header_case_insensitively():
    df = pd.DataFrame({"Cantidad": [1], "Candidato": ["X"]})
    assert _map_col(df, ["cantidad", "monto", "amount"]) == "Cantidad"
    assert _map_col(df, ["no_such_col"]) is None


@pytest.mark.unit
def test_parse_df_maps_spanish_headers_to_canonical_schema():
    df = pd.DataFrame({
        "nombre_donante": ["Juan Perez", "Maria Lopez"],
        "cantidad": ["500", "1000"],
        "fecha_donacion": ["2024-03-01", "2024-03-15"],
        "candidato": ["Pedro Pierluisi", "Jenniffer Gonzalez"],
        "partido": ["PNP", "PNP"],
    })
    out = _parse_df(df, "cee_2024.csv")
    assert list(out.columns) == OUTPUT_COLUMNS
    assert len(out) == 2
    row = out.iloc[0]
    assert row["donor_name"] == "Juan Perez"
    assert row["amount"] == "500"
    assert row["contribution_date"] == "2024-03-01"
    assert row["candidate_or_committee"] == "Pedro Pierluisi"
    assert row["party"] == "PNP"
    assert row["source_file"] == "cee_2024.csv"


@pytest.mark.unit
def test_parse_df_drops_rows_without_donor_name():
    df = pd.DataFrame({
        "nombre_donante": ["Juan Perez", "", "  "],
        "cantidad": ["500", "200", "300"],
    })
    out = _parse_df(df, "f.csv")
    assert len(out) == 1
    assert out.iloc[0]["donor_name"] == "Juan Perez"


@pytest.mark.unit
def test_parse_df_fills_missing_columns_with_empty_string():
    df = pd.DataFrame({"nombre_donante": ["Solo Name"]})
    out = _parse_df(df, "minimal.csv")
    assert list(out.columns) == OUTPUT_COLUMNS
    assert out.iloc[0]["amount"] == ""
    assert out.iloc[0]["party"] == ""


# ---------------------------------------------------------------------------
# Integration: full drop-file -> processed chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_run_materializes_processed_output_from_dropzone(tmp_path: Path):
    drop = tmp_path / "data" / "raw" / "Donaciones"
    drop.mkdir(parents=True)
    with (drop / "cee_2024.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["nombre_donante", "cantidad", "fecha_donacion", "candidato", "partido"])
        w.writerow(["Juan Perez", "500", "2024-03-01", "Pedro Pierluisi", "PNP"])
        w.writerow(["Maria Lopez", "1000", "2024-03-15", "Jenniffer Gonzalez", "PNP"])

    result = run(root=tmp_path)
    assert result["rows"] == 2
    assert result["status"] == "OK"

    out_path = tmp_path / "data" / "staging" / "processed" / "pr_donaciones.csv"
    assert out_path.exists()
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == OUTPUT_COLUMNS
    assert {r["donor_name"] for r in rows} == {"Juan Perez", "Maria Lopez"}


@pytest.mark.integration
def test_run_with_no_dropzone_writes_empty_header_only(tmp_path: Path):
    result = run(root=tmp_path)
    assert result["rows"] == 0
    assert result["status"] == "NO_FILES"
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_donaciones.csv"
    assert out_path.exists()
    assert list(csv.DictReader(out_path.open(encoding="utf-8"))) == []


@pytest.mark.integration
def test_run_caches_existing_output(tmp_path: Path):
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_donaciones.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        w.writeheader()
        w.writerow({c: "x" if c == "donor_name" else "" for c in OUTPUT_COLUMNS})

    result = run(root=tmp_path)
    assert result["status"] == "CACHED"
    assert result["rows"] == 1
