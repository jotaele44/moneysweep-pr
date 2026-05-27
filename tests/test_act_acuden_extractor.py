"""Tests for scripts.extract_act_acuden_pdfs.

The fixture PDFs are generated on the fly with ``reportlab`` (a test-only
dependency) so the repo stays binary-clean. They contain a single tabular
page with a header row and two data rows; that is enough to exercise the
column-mapping, alias-override, and determinism contracts.
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

reportlab = pytest.importorskip("reportlab")
from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import letter  # noqa: E402
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle  # noqa: E402

from scripts.extract_act_acuden_pdfs import (  # noqa: E402
    ACT_COLUMNS,
    ACUDEN_COLUMNS,
    SOURCES,
    extract,
    extract_source,
)


def _build_pdf(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    table = Table([header, *rows])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ]
        )
    )
    doc.build([table])


@pytest.fixture
def act_repo(tmp_path: Path) -> Path:
    """Repo layout with one ACT PDF in the expected drop dir."""
    pdf_path = tmp_path / SOURCES["act"]["input_dir"] / "act_sample.pdf"
    _build_pdf(
        pdf_path,
        header=[
            "contractor name",
            "contract number",
            "start date",
            "end date",
            "amount",
            "service type",
        ],
        rows=[
            [
                "LPC Contractors, Inc.",
                "ACT-001",
                "2022-01-01",
                "2024-12-31",
                "1500000",
                "Highway maintenance",
            ],
            [
                "Super Asphalt Pavement",
                "ACT-002",
                "2023-03-15",
                "2025-03-14",
                "750000",
                "Paving",
            ],
        ],
    )
    return tmp_path


@pytest.fixture
def acuden_repo(tmp_path: Path) -> Path:
    pdf_path = tmp_path / SOURCES["acuden"]["input_dir"] / "acuden_sample.pdf"
    _build_pdf(
        pdf_path,
        header=[
            "contract number",
            "contractor",
            "start date",
            "end date",
            "amount",
            "service type",
        ],
        rows=[
            [
                "ACUDEN-100",
                "Daycare Operator A",
                "2024-01-01",
                "2024-12-31",
                "200000",
                "Daycare services",
            ],
        ],
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Schema contracts
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_act_columns_match_registry() -> None:
    # Mirrors manual_export_registry.yaml act_transition_contracts schema.
    assert ACT_COLUMNS == [
        "contractor_name",
        "contract_number",
        "start_date",
        "end_date",
        "amount",
        "service_type",
    ]


@pytest.mark.unit
def test_acuden_columns_match_registry() -> None:
    assert ACUDEN_COLUMNS == [
        "contract_number",
        "contractor_name",
        "start_date",
        "end_date",
        "amount",
        "service_type",
    ]


# ---------------------------------------------------------------------------
# Integration: extractor end-to-end on synthetic PDFs
# ---------------------------------------------------------------------------

@pytest.mark.integration
def test_extract_act_emits_canonical_columns(act_repo: Path) -> None:
    summary = extract(source="act", root=act_repo)
    info = summary["act"]
    assert info["pdfs"] == 1
    assert info["rows"] == 2
    assert len(info["outputs"]) == 1

    out_path = Path(info["outputs"][0])
    assert out_path.exists()
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert [r for r in rows]  # non-empty
    assert list(rows[0].keys()) == ACT_COLUMNS


@pytest.mark.integration
def test_extract_acuden_emits_canonical_columns(acuden_repo: Path) -> None:
    summary = extract(source="acuden", root=acuden_repo)
    info = summary["acuden"]
    assert info["pdfs"] == 1
    assert info["rows"] == 1

    out_path = Path(info["outputs"][0])
    rows = list(csv.DictReader(out_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == ACUDEN_COLUMNS
    assert rows[0]["contractor_name"] == "Daycare Operator A"
    assert rows[0]["contract_number"] == "ACUDEN-100"


@pytest.mark.integration
def test_extractor_is_deterministic(act_repo: Path) -> None:
    """Two runs over the same PDF must produce byte-identical CSV output."""
    summary_a = extract(source="act", root=act_repo)
    out_path = Path(summary_a["act"]["outputs"][0])
    first_bytes = out_path.read_bytes()

    summary_b = extract(source="act", root=act_repo)
    second_bytes = Path(summary_b["act"]["outputs"][0]).read_bytes()
    assert first_bytes == second_bytes


@pytest.mark.integration
def test_extractor_applies_alias_overrides(act_repo: Path, monkeypatch) -> None:
    """contractor_name must be canonicalized via the alias-override registry."""
    overrides = {
        "LPC CONTRACTORS": "LPC AND D",
        "SUPER ASPHALT PAVEMENT": "SUPER ASPHALT",
    }
    monkeypatch.setattr(
        "scripts.extract_act_acuden_pdfs.load_overrides", lambda: overrides
    )
    summary = extract(source="act", root=act_repo)
    out_path = Path(summary["act"]["outputs"][0])
    names = [
        r["contractor_name"]
        for r in csv.DictReader(out_path.open(encoding="utf-8"))
    ]
    assert "LPC AND D" in names
    assert "SUPER ASPHALT" in names


@pytest.mark.integration
def test_extractor_dry_run_writes_nothing(act_repo: Path) -> None:
    summary = extract(source="act", root=act_repo, dry_run=True)
    info = summary["act"]
    assert info["pdfs"] == 1
    assert info["outputs"] == []
    out_dir = act_repo / SOURCES["act"]["output_dir"]
    assert not out_dir.exists() or not any(out_dir.iterdir())


@pytest.mark.integration
def test_extract_all_handles_missing_drop_dirs(tmp_path: Path) -> None:
    """No drop dirs → both sources report zero PDFs cleanly."""
    summary = extract(source="all", root=tmp_path)
    assert summary["act"]["pdfs"] == 0
    assert summary["acuden"]["pdfs"] == 0
    assert summary["act"]["skipped"]  # missing dir was logged


@pytest.mark.unit
def test_input_dir_requires_explicit_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        extract(source="all", root=tmp_path, input_dir=tmp_path)
