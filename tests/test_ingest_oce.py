"""Tests for the OCE (Oficina del Contralor Electoral) dropzone ingest."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts import ingest_oce


@pytest.mark.unit
def test_no_raw_dir_writes_empty_header(tmp_path):
    result = ingest_oce.run(root=tmp_path, force=True)
    assert result["status"] == "NO_FILES"
    out = pd.read_csv(Path(result["path"]))
    assert list(out.columns) == ingest_oce.OUTPUT_COLUMNS
    assert len(out) == 0


@pytest.mark.unit
def test_spanish_column_mapping(tmp_path):
    raw = tmp_path / "data" / "raw" / "OCE"
    raw.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "Nombre_Donante": "Civic Trust",
                "Cantidad": "2500",
                "Fecha": "2024-09-01",
                "Comite": "Comite OCE",
                "Partido": "PNP",
                "Ciudad": "Bayamon",
            },
            {
                "Nombre_Donante": "",  # filtered out (no donor name)
                "Cantidad": "100",
                "Fecha": "2024-09-02",
                "Comite": "Other",
                "Partido": "PPD",
                "Ciudad": "San Juan",
            },
        ]
    ).to_csv(raw / "oce_2024.csv", index=False)

    result = ingest_oce.run(root=tmp_path, force=True)
    assert result["status"] == "OK"
    assert result["rows"] == 1
    out = pd.read_csv(Path(result["path"]), dtype=str)
    row = out.iloc[0]
    assert row["donor_name"] == "Civic Trust"
    assert row["amount"] == "2500"
    assert row["party"] == "PNP"
    assert row["candidate_or_committee"] == "Comite OCE"
    assert row["donor_city"] == "Bayamon"
    assert row["source_file"] == "oce_2024.csv"


@pytest.mark.unit
def test_cached_output_short_circuits(tmp_path):
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_oce_donations.csv"
    out_path.parent.mkdir(parents=True)
    pd.DataFrame(
        [{c: ("X" if c == "donor_name" else "") for c in ingest_oce.OUTPUT_COLUMNS}]
    ).to_csv(out_path, index=False)
    result = ingest_oce.run(root=tmp_path, force=False)
    assert result["status"] == "CACHED"
    assert result["rows"] == 1
