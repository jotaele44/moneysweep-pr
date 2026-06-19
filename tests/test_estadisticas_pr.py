"""Tests for the Datos.PR CKAN fiscal-revenue producer (scripts.download_estadisticas_pr).

Hermetic: HTTP is mocked, so normalization + the no-egress graceful path are exercised
without network. Mirrors the buildout environment where egress is blocked.
"""

from __future__ import annotations

import csv
from unittest.mock import MagicMock

import pytest

import scripts.download_estadisticas_pr as mod
from scripts.download_estadisticas_pr import CANONICAL_COLUMNS, SOURCES, _normalize, run

pytestmark = pytest.mark.unit


def _json_resp(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


def test_normalize_maps_spanish_fields_and_is_deterministic():
    records = [
        {
            "_id": 2,
            "periodo": "2024-02",
            "fuente": "Contribución sobre Ingresos",
            "ingresos_netos": "3,450,000.00",
        },
        {"_id": 1, "periodo": "2024-01", "fuente": "Act 154", "ingresos_netos": "$1,250,000"},
        {"_id": 3, "periodo": "", "fuente": "", "ingresos_netos": ""},  # dropped (all empty)
    ]
    rows = _normalize(records, "pr_general_fund_revenues")
    assert [r["period"] for r in rows] == ["2024-01", "2024-02"]  # sorted, empty dropped
    assert rows[0]["category"] == "Act 154"
    assert rows[0]["amount_usd"] == "1250000.0"
    assert all(r["source_system"] == "pr_general_fund_revenues" for r in rows)
    assert list(rows[0].keys()) == CANONICAL_COLUMNS


def test_run_materializes_from_mocked_ckan(tmp_path, monkeypatch):
    """package_search -> datastore_search happy path, mocked end to end."""

    def fake_get(url, params=None, timeout=None):
        if "package_search" in url:
            return _json_resp(
                {
                    "success": True,
                    "result": {
                        "results": [{"resources": [{"id": "res-1", "datastore_active": True}]}]
                    },
                }
            )
        if "datastore_search" in url:
            return _json_resp(
                {
                    "success": True,
                    "result": {
                        "total": 2,
                        "records": [
                            {"_id": 1, "periodo": "2024-01", "concepto": "IVU", "monto": "500000"},
                            {
                                "_id": 2,
                                "periodo": "2024-01",
                                "concepto": "Act 154",
                                "monto": "1200000",
                            },
                        ],
                    },
                }
            )
        return _json_resp({"success": False})

    session = MagicMock()
    session.get.side_effect = fake_get
    monkeypatch.setattr(mod, "_session", lambda: session)

    result = run(root=tmp_path, source="pr_general_fund_revenues")
    assert result["status"] == "OK"
    assert result["rows"] == 2

    out = tmp_path / SOURCES["pr_general_fund_revenues"]["output"]
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert [r["category"] for r in rows] == ["Act 154", "IVU"]  # sorted by (period, category)
    assert list(rows[0].keys()) == CANONICAL_COLUMNS


def test_run_no_egress_writes_empty_schema_without_raising(tmp_path, monkeypatch):
    """Network failure -> EMPTY status, empty-schema CSV, no exception (preflight-safe)."""
    session = MagicMock()
    session.get.side_effect = mod.requests.ConnectionError("no egress")
    monkeypatch.setattr(mod, "_session", lambda: session)
    # Suppress retry-backoff sleeps (5s + 15s per failed attempt) so the test
    # does not take 20+ seconds on the FUSE-mounted sandbox filesystem.
    monkeypatch.setattr("time.sleep", lambda _: None)

    result = run(root=tmp_path, source="pr_income_tax_collections")
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0

    out = tmp_path / SOURCES["pr_income_tax_collections"]["output"]
    assert out.exists()
    with out.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        assert header == CANONICAL_COLUMNS
        assert next(reader, None) is None  # header only


def test_module_imports_without_network():
    """Preflight imports every producer; this must not require egress."""
    assert callable(mod.run)
    assert callable(mod.main)
    assert set(SOURCES) == {
        "pr_general_fund_revenues",
        "pr_income_tax_collections",
        "estadisticas_pr_external_trade",
    }
