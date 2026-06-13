"""Tests for shared source-intake helpers."""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest

from scripts.source_intake_helpers import (
    discover_tabular_files,
    load_tabular_dropzone,
    map_frame,
    normalize_name,
    read_csv_rows,
    write_canonical_csv,
)


@pytest.mark.unit
def test_normalize_name_strips_suffixes_and_punctuation():
    assert normalize_name("Acme Contractors, LLC") == "ACME CONTRACTORS"
    assert normalize_name("Puerto Rico Builders Inc.") == "PUERTO RICO BUILDERS"
    assert normalize_name("") == ""


@pytest.mark.unit
def test_discover_tabular_files_ignores_temp_and_unsupported_files(tmp_path: Path):
    drop = tmp_path / "drop"
    drop.mkdir()
    (drop / "a.csv").write_text("x\n1\n", encoding="utf-8")
    (drop / "~temp.csv").write_text("x\n2\n", encoding="utf-8")
    (drop / "note.txt").write_text("x\n", encoding="utf-8")
    assert [p.name for p in discover_tabular_files(drop)] == ["a.csv"]


@pytest.mark.unit
def test_map_frame_adds_provenance_and_excerpt():
    frame = pd.DataFrame({"Contract ID": ["C-1"], "Contratista": ["Acme LLC"]})
    out = map_frame(
        frame,
        {"contract_id": ["Contract ID"], "contractor_name": ["Contratista"]},
        ["source_id", "source_file", "contract_id", "contractor_name", "raw_text_excerpt", "evidence_tier", "confidence"],
        "test_source",
        "input.csv",
    )
    row = out.iloc[0].to_dict()
    assert row["source_id"] == "test_source"
    assert row["source_file"] == "input.csv"
    assert row["contract_id"] == "C-1"
    assert row["contractor_name"] == "Acme LLC"
    assert row["evidence_tier"] == "T2"
    assert row["confidence"] == "0.70"
    assert "Acme LLC" in row["raw_text_excerpt"]


@pytest.mark.integration
def test_load_and_write_round_trip_csv(tmp_path: Path):
    drop = tmp_path / "drop"
    drop.mkdir()
    with (drop / "source.csv").open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Name"])
        writer.writerow(["Alpha"])

    loaded = load_tabular_dropzone(drop)
    assert len(loaded) == 1
    assert loaded[0].frame.iloc[0]["Name"] == "Alpha"

    out = tmp_path / "out.csv"
    write_canonical_csv(pd.DataFrame([{"name": "Alpha"}]), out, ["name"])
    assert read_csv_rows(out) == [{"name": "Alpha"}]
