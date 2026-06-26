from __future__ import annotations

import json
from pathlib import Path

import pytest

from moneysweep.runtime import source_registry as sr
from scripts.probe_legislapr_detail import measure_id_from_url, parse_legislapr_detail

REPO_ROOT = Path(__file__).resolve().parents[1]


SAMPLE_HTML = """
<html>
  <head>
    <title>PS 782 - Medida fiscal</title>
    <meta name="description" content="Medida legislativa con asignaciones de fondos." />
  </head>
  <body>
    <h1>PS 782</h1>
    <p>Estado: Radicado</p>
    <p>Cámara: Senado</p>
    <p>Sesión: 20ma Asamblea Legislativa</p>
    <p>Tipo: Proyecto del Senado</p>
    <p>Autores: Sen. Jane Doe, Sen. John Roe</p>
    <p>Resumen: Asigna fondos y contratos relacionados.</p>
    <a href="https://openstates.org/pr/bills/2025-2028/PS782/">OpenStates</a>
    <a href="https://sutra.oslpr.org/medidas/ps0782-25.doc">Texto oficial SUTRA</a>
  </body>
</html>
"""


@pytest.mark.unit
def test_legislapr_source_registry_extension_loaded():
    src = sr.source_by_id("legislapr_discovery", REPO_ROOT)
    assert src is not None
    assert src["family"] == "territorial_legislation"
    assert src["required"] is False
    assert src["authentication"] == "none"
    assert src["producer_script"] == "scripts/probe_legislapr_detail.py"
    assert src["promotion_rule"] == "cross_confirmed_only"
    assert src["canonical_source_required"] is True


@pytest.mark.unit
def test_legislapr_schema_extension_declares_measure_table():
    path = REPO_ROOT / "registries" / "schema_registry_extensions" / "legislapr_legislative_measure.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    table = data["canonical_tables"]["legislative_measures"]
    assert table["primary_key"] == ["measure_id", "source_system"]
    column_names = {column["name"] for column in table["columns"]}
    assert "openstates_url" in column_names
    assert "sutra_url" in column_names
    assert "promotion_status" in column_names
    assert "fiscal_language_detected" in column_names


@pytest.mark.unit
def test_measure_id_from_legislapr_url_is_canonicalized():
    assert measure_id_from_url("https://www.legislapr.com/bills/PS%20782") == "PS782"
    assert measure_id_from_url("https://www.legislapr.com/bills/P%20del%20C%20123") == "PC123"


@pytest.mark.unit
def test_parse_legislapr_detail_requires_cross_confirmation_for_candidate():
    row = parse_legislapr_detail(SAMPLE_HTML, "https://www.legislapr.com/bills/PS%20782")
    assert row.measure_id == "PS782"
    assert row.source_system == "legislapr_discovery"
    assert row.openstates_url.startswith("https://openstates.org/")
    assert "sutra.oslpr.org" in row.sutra_url
    assert row.fiscal_language_detected is True
    assert row.promotion_status == "cross_confirmed_candidate"
    assert row.extraction_confidence >= 0.8


@pytest.mark.unit
def test_parse_legislapr_detail_blocks_unconfirmed_records():
    row = parse_legislapr_detail("<html><title>PS 782</title><p>Presupuesto y fondos</p></html>", "https://www.legislapr.com/bills/PS%20782")
    assert row.fiscal_language_detected is True
    assert row.openstates_url == ""
    assert row.sutra_url == ""
    assert row.promotion_status == "blocked_pending_canonical_confirmation"
    assert row.extraction_confidence < 0.8
