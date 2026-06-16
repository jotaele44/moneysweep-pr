"""Tests for the Census government-finance and FTA NTD producers.

Hermetic: HTTP is mocked, so 2-D-array / Socrata parsing, PR filtering, and the
no-egress/no-key graceful paths are exercised without network.
"""

from __future__ import annotations

import csv
from unittest.mock import MagicMock

import pytest

import scripts.download_census_gov_finances as census
import scripts.download_fta_ntd as ntd

pytestmark = pytest.mark.unit


def _resp(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


# --------------------------- Census ---------------------------


def test_census_rows_from_2d_and_normalize():
    payload = [
        ["NAME", "AMOUNT", "AGG_DESC", "YEAR", "state"],
        ["Puerto Rico", "1,250,000", "Total Taxes", "2023", "72"],
        ["Puerto Rico", "$500,000", "Sales Tax", "2023", "72"],
    ]
    rows = census.normalize(census._rows_from_2d(payload))
    assert [r["category"] for r in rows] == ["Sales Tax", "Total Taxes"]  # sorted
    assert rows[0]["amount_usd"] == "500000.0"
    assert all(r["source_system"] == "census_gov_finances" for r in rows)
    assert list(rows[0].keys()) == census.CANONICAL_COLUMNS


def test_census_no_key_is_empty_without_network(tmp_path, monkeypatch):
    monkeypatch.delenv("CENSUS_API_KEY", raising=False)
    called = {"n": 0}
    monkeypatch.setattr(census, "_session", lambda: called.__setitem__("n", 1) or MagicMock())
    result = census.run(root=tmp_path)
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    assert called["n"] == 0  # no session/network when key missing
    out = tmp_path / census.OUTPUT
    with out.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == census.CANONICAL_COLUMNS


def test_census_run_with_mocked_api(tmp_path, monkeypatch):
    monkeypatch.setenv("CENSUS_API_KEY", "k")
    session = MagicMock()
    session.get.return_value = _resp(
        [["NAME", "AMOUNT", "AGG_DESC"], ["Puerto Rico", "999", "Property Tax"]]
    )
    monkeypatch.setattr(census, "_session", lambda: session)
    result = census.run(root=tmp_path)
    assert result["status"] == "OK"
    assert result["rows"] == 1


# --------------------------- FTA NTD ---------------------------


def test_ntd_pr_filter_and_normalize():
    recs = [
        {
            "report_year": "2023",
            "agency": "Puerto Rico Highway and Transportation Authority",
            "operating_expenses": "10,000",
        },
        {"report_year": "2023", "agency": "Metro Transit (MN)", "operating_expenses": "50,000"},
    ]
    pr = [r for r in recs if ntd._is_pr(r)]
    assert len(pr) == 1
    rows = ntd.normalize(pr)
    assert rows[0]["category"].startswith("Puerto Rico")
    assert rows[0]["amount_usd"] == "10000.0"
    assert rows[0]["source_system"] == "fta_ntd"


def test_ntd_run_no_resource_id_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(ntd, "NTD_RESOURCE_ID", "")
    monkeypatch.setattr(ntd, "_session", lambda: MagicMock())
    result = ntd.run(root=tmp_path)
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    out = tmp_path / ntd.OUTPUT
    with out.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == ntd.CANONICAL_COLUMNS


def test_ntd_run_with_mocked_socrata(tmp_path, monkeypatch):
    monkeypatch.setattr(ntd, "NTD_RESOURCE_ID", "abcd-1234")
    session = MagicMock()
    session.get.side_effect = [
        _resp([{"report_year": "2024", "agency": "PRITA Puerto Rico", "total_funding": "1234567"}]),
        _resp([]),
    ]
    monkeypatch.setattr(ntd, "_session", lambda: session)
    result = ntd.run(root=tmp_path)
    assert result["status"] == "OK"
    assert result["rows"] == 1
