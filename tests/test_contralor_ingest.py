"""Tests for the PR Contralor (OCPR) audit-report ingester (scripts.ingest_contralor).

Covers the pure header-mapping / name-normalization transform and the full
drop-file -> processed-CSV chain. The ingester reads operator-delivered CSV/Excel
exports from a dropzone (no network), so these run fully offline.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_contralor import (
    CONTRALOR_COLUMNS,
    _normalize_name,
    _parse_df,
    run,
)

# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_name_strips_punctuation_and_entity_suffixes():
    assert _normalize_name("Autopistas de PR, Inc.") == "AUTOPISTAS"
    assert _normalize_name("Acme Corp") == "ACME"
    assert _normalize_name("") == ""


@pytest.mark.unit
def test_parse_df_maps_spanish_headers_to_canonical_schema():
    df = pd.DataFrame(
        {
            "Entidad": ["Municipio de Ponce", "ACME LLC"],
            "Número de Informe": ["M-24-15", "CP-23-02"],
            "Tipo de Informe": ["Auditoría", "Cumplimiento"],
            "Año": ["2024", "2023"],
            "Hallazgos": ["3", "0"],
            "Monto": ["1500000", "0"],
            "Estado": ["Abierto", "Cerrado"],
        }
    )
    out = _parse_df(df, "informe_2024.csv", logger=_NullLogger())
    assert list(out.columns) == CONTRALOR_COLUMNS
    assert len(out) == 2
    row = out.iloc[0]
    assert row["entity_name"] == "Municipio de Ponce"
    assert row["audit_id"] == "M-24-15"
    assert row["finding_count"] == "3"
    assert row["source_file"] == "informe_2024.csv"
    assert row["entity_normalized"] == "MUNICIPIO DE PONCE"


@pytest.mark.unit
def test_parse_df_drops_rows_without_entity():
    df = pd.DataFrame(
        {"Entidad": ["Real Entity", "", "  "], "Número de Informe": ["A1", "A2", "A3"]}
    )
    out = _parse_df(df, "f.csv", logger=_NullLogger())
    assert len(out) == 1
    assert out.iloc[0]["entity_name"] == "Real Entity"


# ---------------------------------------------------------------------------
# Integration: full drop-file -> processed chain
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_materializes_processed_output_from_dropzone(tmp_path: Path):
    drop = tmp_path / "data" / "raw" / "Oficina del Contralor"
    drop.mkdir(parents=True)
    with (drop / "informes.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Entidad", "Número de Informe", "Año", "Hallazgos", "Estado"])
        w.writerow(["Municipio de Caguas", "M-24-01", "2024", "5", "Abierto"])
        w.writerow(["Autoridad de Energía", "CP-24-09", "2024", "2", "Cerrado"])

    result = run(root=tmp_path)
    assert result["rows"] == 2

    out_path = tmp_path / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    assert out_path.exists()
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == CONTRALOR_COLUMNS
    assert {r["entity_name"] for r in rows} == {"Municipio de Caguas", "Autoridad de Energía"}


@pytest.mark.integration
def test_run_with_no_dropzone_writes_empty_header_only(tmp_path: Path):
    result = run(root=tmp_path)
    assert result["rows"] == 0
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    assert out_path.exists()
    assert list(csv.DictReader(out_path.open(encoding="utf-8"))) == []


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass
