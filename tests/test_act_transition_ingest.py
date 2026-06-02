"""Tests for the ACT/ACUDEN promote producer (scripts.ingest_act_transition).

Unit tests cover the pure ``promote_rows`` transform; an integration test drives
the full ``run()`` chain (drop PDF → extract → promote → processed CSV) against a
reportlab-generated PDF, mirroring tests/test_act_acuden_extractor.py. No network.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.ingest_act_transition import (
    CANONICAL_COLUMNS,
    PROCESSED_OUTPUTS,
    promote_rows,
    run,
)

# ---------------------------------------------------------------------------
# Unit: pure promote transform
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_promote_rows_maps_to_canonical_schema():
    rows = [{"contractor_name": "LPC", "contract_number": "2020-000123",
             "start_date": "2020-01-01", "end_date": "2025-01-01",
             "amount": "$1,000", "service_type": "Eng"}]
    out = promote_rows(rows, "act")
    assert len(out) == 1
    assert list(out[0].keys()) == CANONICAL_COLUMNS
    assert out[0]["source_dataset"] == "act_transition_contracts"
    assert out[0]["contract_number"] == "2020-000123"


@pytest.mark.unit
def test_promote_rows_drops_empty_and_dedupes():
    rows = [
        {"contractor_name": "ACME", "contract_number": "C1"},
        {"contractor_name": "ACME", "contract_number": "C1"},   # dup
        {"contractor_name": "", "contract_number": ""},          # empty → dropped
    ]
    out = promote_rows(rows, "acuden")
    assert len(out) == 1
    assert out[0]["source_dataset"] == "acuden_2024_transition"


@pytest.mark.unit
def test_run_with_no_drop_dir_is_clean_noop(tmp_path: Path):
    result = run(root=tmp_path)
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    # Nothing written when no operator file is present.
    assert not (tmp_path / PROCESSED_OUTPUTS["act"]).exists()


# ---------------------------------------------------------------------------
# Integration: full drop-PDF → processed chain
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_run_materializes_processed_output_from_pdf(tmp_path: Path):
    reportlab = pytest.importorskip("reportlab")
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle

    pdf_path = tmp_path / "data" / "manual" / "act_transition" / "act_sample.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(pdf_path), pagesize=letter)
    table = Table([
        ["contractor name", "contract number", "start date", "end date", "amount", "service type"],
        ["LPC Contractors, Inc.", "ACT-001", "2022-01-01", "2024-12-31", "1500000", "Highway maintenance"],
        ["Super Asphalt Pavement", "ACT-002", "2023-03-15", "2025-03-14", "750000", "Paving"],
    ])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
    ]))
    doc.build([table])

    result = run(root=tmp_path, source="act")
    assert result["status"] == "OK"
    assert result["rows"] >= 1

    out_path = tmp_path / PROCESSED_OUTPUTS["act"]
    assert out_path.exists()
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert rows and list(rows[0].keys()) == CANONICAL_COLUMNS
    assert all(r["source_dataset"] == "act_transition_contracts" for r in rows)
