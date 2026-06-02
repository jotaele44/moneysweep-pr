"""Tests for the PRASA (Puerto Rico Aqueduct and Sewer Authority) ingester
(scripts.ingest_prasa).

Covers the pure header-mapping / name-normalization transform and the full
drop-file -> processed-CSV chain. The ingester reads operator-delivered CSV/Excel
procurement exports from a dropzone (no network), so these run fully offline.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_prasa import (
    PRASA_COLUMNS,
    _normalize_name,
    _parse_df,
    run,
)

# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_normalize_name_strips_punctuation_and_entity_suffixes():
    assert _normalize_name("Acueductos de PR, Inc.") == "ACUEDUCTOS DE PR"
    assert _normalize_name("Acme Corp") == "ACME"
    assert _normalize_name("") == ""


@pytest.mark.unit
def test_parse_df_maps_spanish_headers_to_canonical_schema():
    df = pd.DataFrame({
        "Contratista": ["Acme LLC", "Municipio de Ponce"],
        "Número de Contrato": ["P-24-15", "P-23-02"],
        "Tipo de Contrato": ["Servicios", "Construcción"],
        "Monto": ["1500000", "250000"],
        "Fecha de Adjudicación": ["2024-01-15", "2023-06-01"],
        "Estado": ["Activo", "Cerrado"],
        "Municipio": ["San Juan", "Ponce"],
    })
    out = _parse_df(df, "contratos_2024.csv", logger=_NullLogger())
    assert list(out.columns) == PRASA_COLUMNS
    assert len(out) == 2
    row = out.iloc[0]
    assert row["vendor_name"] == "Acme LLC"
    assert row["contract_id"] == "P-24-15"
    assert row["contract_value"] == "1500000"
    assert row["municipality"] == "San Juan"
    assert row["source_file"] == "contratos_2024.csv"
    assert row["vendor_normalized"] == "ACME"


@pytest.mark.unit
def test_parse_df_drops_rows_without_vendor():
    df = pd.DataFrame({"Contratista": ["Real Vendor", "", "  "],
                       "Número de Contrato": ["A1", "A2", "A3"]})
    out = _parse_df(df, "f.csv", logger=_NullLogger())
    assert len(out) == 1
    assert out.iloc[0]["vendor_name"] == "Real Vendor"


# ---------------------------------------------------------------------------
# Integration: full drop-file -> processed chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_run_materializes_processed_output_from_dropzone(tmp_path: Path):
    drop = tmp_path / "data" / "raw" / "PRASA"
    drop.mkdir(parents=True)
    with (drop / "contratos.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Contratista", "Número de Contrato", "Monto", "Estado"])
        w.writerow(["Acme LLC", "P-24-01", "1000000", "Activo"])
        w.writerow(["Beta Corp", "P-24-09", "500000", "Cerrado"])

    result = run(root=tmp_path)
    assert result["rows"] == 2

    out_path = tmp_path / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    assert out_path.exists()
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == PRASA_COLUMNS
    assert {r["vendor_name"] for r in rows} == {"Acme LLC", "Beta Corp"}


@pytest.mark.integration
def test_run_with_no_dropzone_writes_empty_header_only(tmp_path: Path):
    result = run(root=tmp_path)
    assert result["rows"] == 0
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_prasa_contracts.csv"
    assert out_path.exists()
    assert list(csv.DictReader(out_path.open(encoding="utf-8"))) == []


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass
