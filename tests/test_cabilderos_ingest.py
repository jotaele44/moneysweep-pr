"""Tests for the PR Cabilderos (state lobbyist registry) ingester
(scripts.ingest_cabilderos).

Covers the pure header-mapping / name-normalization transform and the full
drop-file -> processed-CSV chain. The ingester reads operator-delivered CSV/Excel
exports from the PR Office of Government Ethics dropzone (no network), so these
run fully offline.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.ingest_cabilderos import (
    CABILDEROS_COLUMNS,
    _normalize_name,
    _parse_df,
    run,
)

# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_normalize_name_strips_punctuation_and_entity_suffixes():
    assert _normalize_name("Estrategias Group, Inc.") == "ESTRATEGIAS GROUP"
    assert _normalize_name("Acme Corp") == "ACME"
    assert _normalize_name("") == ""


@pytest.mark.unit
def test_parse_df_maps_spanish_headers_to_canonical_schema():
    df = pd.DataFrame(
        {
            "Nombre Cabildero": ["Juan Perez", "Maria Lopez"],
            "Cliente": ["Acme LLC", "Beta Foundation"],
            "Año": ["2024", "2023"],
            "Agencia": ["Senado", "Cámara"],
            "Honorarios": ["50000", "30000"],
        }
    )
    out = _parse_df(df, "cabilderos_2024.csv", logger=_NullLogger())
    assert list(out.columns) == CABILDEROS_COLUMNS
    assert len(out) == 2
    row = out.iloc[0]
    assert row["lobbyist_name"] == "Juan Perez"
    assert row["client_name"] == "Acme LLC"
    assert row["registration_year"] == "2024"
    assert row["agency_lobbied"] == "Senado"
    assert row["source_file"] == "cabilderos_2024.csv"
    assert row["lobbyist_normalized"] == "JUAN PEREZ"
    assert row["client_normalized"] == "ACME"


@pytest.mark.unit
def test_parse_df_drops_rows_without_client():
    df = pd.DataFrame(
        {"Nombre Cabildero": ["Lob A", "Lob B", "Lob C"], "Cliente": ["Real Client", "", "  "]}
    )
    out = _parse_df(df, "f.csv", logger=_NullLogger())
    assert len(out) == 1
    assert out.iloc[0]["client_name"] == "Real Client"


# ---------------------------------------------------------------------------
# Integration: full drop-file -> processed chain
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_run_materializes_processed_output_from_dropzone(tmp_path: Path):
    drop = tmp_path / "data" / "raw" / "Cabilderos"
    drop.mkdir(parents=True)
    with (drop / "registro.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Nombre Cabildero", "Cliente", "Año", "Agencia"])
        w.writerow(["Juan Perez", "Acme LLC", "2024", "Senado"])
        w.writerow(["Maria Lopez", "Beta Foundation", "2024", "Cámara"])

    result = run(root=tmp_path)
    assert result["rows"] == 2

    out_path = tmp_path / "data" / "staging" / "processed" / "pr_cabilderos.csv"
    assert out_path.exists()
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == CABILDEROS_COLUMNS
    assert {r["client_name"] for r in rows} == {"Acme LLC", "Beta Foundation"}


@pytest.mark.integration
def test_run_with_no_dropzone_writes_empty_header_only(tmp_path: Path):
    result = run(root=tmp_path)
    assert result["rows"] == 0
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_cabilderos.csv"
    assert out_path.exists()
    assert list(csv.DictReader(out_path.open(encoding="utf-8"))) == []


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass
