"""Offline transform tests for the EIA and FRED time-series downloaders.

These exercise the pure API-response → row mapping (and EIA period
normalization / param building) with fixtures only — no network, no API key.
The live HTTP path is intentionally not exercised here.
"""

from __future__ import annotations

import scripts.download_eia as E
import scripts.download_fred as F


# --------------------------------------------------------------------------
# EIA — _normalize_period
# --------------------------------------------------------------------------


def test_eia_normalize_period_monthly():
    assert E._normalize_period("2024-01", "monthly") == "2024-01-01"
    assert E._normalize_period("2024-12", "monthly") == "2024-12-01"


def test_eia_normalize_period_annual():
    assert E._normalize_period("2024", "annual") == "2024-01-01"


def test_eia_normalize_period_quarterly():
    assert E._normalize_period("2024Q1", "quarterly") == "2024-01-01"
    assert E._normalize_period("2024Q2", "quarterly") == "2024-04-01"
    assert E._normalize_period("2024Q4", "quarterly") == "2024-10-01"


def test_eia_normalize_period_empty():
    assert E._normalize_period("", "monthly") == ""


# --------------------------------------------------------------------------
# EIA — _rows_to_dataframe
# --------------------------------------------------------------------------

_EIA_SERIES = {
    "series_id": "PR-NET-GEN",
    "route": "electricity/electric-power-operational-data",
    "data_field": "generation",
    "units": "thousand MWh",
    "frequency": "monthly",
    "description": "PR net generation",
}


def test_eia_rows_to_dataframe_empty():
    df = E._rows_to_dataframe(_EIA_SERIES, [], "2026-01-01T00:00:00Z")
    assert df.empty
    assert list(df.columns) == E.OUTPUT_COLUMNS


def test_eia_rows_to_dataframe_maps_and_formats():
    rows = [
        {"period": "2024-01", "generation": "1234.567", "generation-units": "MWh"},
        {"period": "2024-02", "generation": "1000.500000"},  # trailing zeros stripped
        {"period": "2024-03", "generation": "."},  # non-numeric -> empty
    ]
    df = E._rows_to_dataframe(_EIA_SERIES, rows, "2026-01-01T00:00:00Z")
    assert list(df.columns) == E.OUTPUT_COLUMNS
    assert len(df) == 3
    first = df.iloc[0]
    assert first["series_id"] == "PR-NET-GEN"
    assert first["date"] == "2024-01-01"
    assert first["value"] == "1234.567"
    assert first["units"] == "MWh"  # row-level override of the YAML units
    assert first["raw_period"] == "2024-01"
    assert first["data_field"] == "generation"
    assert df.iloc[1]["value"] == "1000.5"  # stripped
    assert df.iloc[1]["units"] == "thousand MWh"  # falls back to series units
    assert df.iloc[2]["value"] == ""  # "." -> empty


# --------------------------------------------------------------------------
# EIA — _build_params
# --------------------------------------------------------------------------


def test_eia_build_params_core_and_facets():
    series = {
        "data_field": "generation",
        "frequency": "monthly",
        "facets": {"fueltypeid": ["ALL"], "location": "PR"},
    }
    params = E._build_params("KEY123", series, "2010-01", offset=50)
    assert ("api_key", "KEY123") in params
    assert ("data[0]", "generation") in params
    assert ("frequency", "monthly") in params
    assert ("start", "2010-01") in params
    assert ("offset", "50") in params
    # facets expand to repeated facets[key][] pairs (list and scalar both handled)
    assert ("facets[fueltypeid][]", "ALL") in params
    assert ("facets[location][]", "PR") in params


# --------------------------------------------------------------------------
# FRED — _rows_to_dataframe
# --------------------------------------------------------------------------

_FRED_SERIES = {
    "series_id": "PRUR",
    "description": "PR unemployment rate",
    "units": "percent",
    "frequency": "monthly",
}


def test_fred_rows_to_dataframe_empty():
    df = F._rows_to_dataframe(_FRED_SERIES, [], "2026-01-01T00:00:00Z")
    assert df.empty
    assert list(df.columns) == F.OUTPUT_COLUMNS


def test_fred_rows_to_dataframe_maps_missing_and_formats():
    rows = [
        {"date": "2024-01-01", "value": "3.45"},
        {"date": "2024-02-01", "value": "."},  # FRED missing sentinel -> empty
        {"date": "2024-03-01", "value": "1234.500000"},  # trailing zeros stripped
    ]
    df = F._rows_to_dataframe(_FRED_SERIES, rows, "2026-01-01T00:00:00Z")
    assert list(df.columns) == F.OUTPUT_COLUMNS
    assert len(df) == 3
    assert df.iloc[0]["series_id"] == "PRUR"
    assert df.iloc[0]["date"] == "2024-01-01"  # passthrough, already ISO
    assert df.iloc[0]["raw_date"] == "2024-01-01"
    assert df.iloc[0]["value"] == "3.45"
    assert df.iloc[0]["units"] == "percent"
    assert df.iloc[1]["value"] == ""  # "." -> empty
    assert df.iloc[2]["value"] == "1234.5"  # stripped


# --------------------------------------------------------------------------
# Partial-fetch-failure guard: a hard failure must NOT overwrite the canonical
# CSV with a partial result (regression for the silent-data-loss review).
# --------------------------------------------------------------------------

_PRIOR_CSV = "series_id,date,value\nPRIOR,2020-01-01,42\n"


def test_eia_run_preserves_prior_csv_on_fetch_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(E, "get_eia_api_key", lambda: "TESTKEY")
    monkeypatch.setattr(E, "_fetch_series", lambda *a, **k: ([], False))  # simulate hard failure
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)
    prior = out_dir / E.OUTPUT_PATH.name
    prior.write_text(_PRIOR_CSV, encoding="utf-8")
    result = E.run(root=tmp_path, force=True, only=["pr_net_generation_all_fuels"])
    assert result["status"] == "PARTIAL_FAILURE"
    assert "pr_net_generation_all_fuels" in result.get("failed_series", [])
    assert prior.read_text(encoding="utf-8") == _PRIOR_CSV  # untouched


def test_fred_run_preserves_prior_csv_on_fetch_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(F, "get_fred_api_key", lambda: "TESTKEY")
    monkeypatch.setattr(F, "_fetch_series", lambda *a, **k: ([], False))  # simulate hard failure
    out_dir = tmp_path / "data" / "staging" / "processed"
    out_dir.mkdir(parents=True)
    prior = out_dir / F.OUTPUT_PATH.name
    prior.write_text(_PRIOR_CSV, encoding="utf-8")
    result = F.run(root=tmp_path, force=True, only=["PRLF"])
    assert result["status"] == "PARTIAL_FAILURE"
    assert "PRLF" in result.get("failed_series", [])
    assert prior.read_text(encoding="utf-8") == _PRIOR_CSV  # untouched
