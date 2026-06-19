"""Tests for the EPA ECHO / ICIS-FE&C producer (scripts.download_epa_echo_icis).

Hermetic: HTTP is mocked. Covers ECHO-envelope extraction, penalty/PR normalization, the
opportunistic X-Api-Key header, and the no-egress graceful path.
"""

from __future__ import annotations

import csv
from unittest.mock import MagicMock

import pytest

import scripts.download_epa_echo_icis as echo
from scripts.download_epa_echo_icis import CANONICAL_COLUMNS, extract_records, normalize, run

pytestmark = pytest.mark.unit


def _resp(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


def test_extract_records_tolerates_nested_envelope():
    assert extract_records({"Results": {"Cases": [{"a": 1}]}}) == [{"a": 1}]
    assert extract_records([{"b": 2}]) == [{"b": 2}]
    assert extract_records({"nope": 1}) == []


def test_normalize_maps_penalty_and_is_deterministic():
    recs = [
        {
            "defendant_entity": "PR Aqueduct",
            "fed_penalty_assessed_amt": "$1,000,000",
            "enf_concluded_date": "2023",
        },
        {"fac_name": "ACME PR", "total_penalty": "250000", "settled_date": "2022"},
    ]
    rows = normalize(recs)
    assert [r["period"] for r in rows] == ["2022", "2023"]  # sorted
    assert rows[1]["amount_usd"] == "1000000.0"
    assert all(r["source_system"] == "eqb_epa_icis" for r in rows)
    assert list(rows[0].keys()) == CANONICAL_COLUMNS


def test_run_with_mocked_echo_and_apikey_header(tmp_path, monkeypatch):
    monkeypatch.setenv("X_API_KEY", "rate-limit-key")
    session = MagicMock()
    session.get.return_value = _resp(
        {
            "Results": {
                "Cases": [
                    {"fac_name": "PR Facility", "fed_penalty_assessed_amt": "500000", "fy": "2024"}
                ]
            }
        }
    )
    captured = {}
    session.headers = {}

    def _mk_session():
        # mimic the header set in _session() so we can assert X-Api-Key is applied
        session.headers["X-Api-Key"] = "rate-limit-key"
        captured["headers"] = session.headers
        return session

    monkeypatch.setattr(echo, "_session", _mk_session)
    result = run(root=tmp_path)
    assert result["status"] == "OK"
    assert result["rows"] == 1
    assert captured["headers"].get("X-Api-Key") == "rate-limit-key"

    out = tmp_path / echo.OUTPUT
    with out.open(encoding="utf-8", newline="") as f:
        assert list(csv.DictReader(f))[0]["amount_usd"] == "500000.0"


def test_run_no_egress_writes_empty_without_raising(tmp_path, monkeypatch):
    monkeypatch.delenv("X_API_KEY", raising=False)
    session = MagicMock()
    session.get.side_effect = echo.requests.ConnectionError("no egress")
    monkeypatch.setattr(echo, "_session", lambda: session)
    # Suppress retry-backoff sleeps (5s + 15s per failed attempt) so the test
    # does not take 20+ seconds on the FUSE-mounted sandbox filesystem.
    monkeypatch.setattr("time.sleep", lambda _: None)
    result = run(root=tmp_path)
    assert result["status"] == "EMPTY"
    assert result["rows"] == 0
    out = tmp_path / echo.OUTPUT
    with out.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == CANONICAL_COLUMNS
