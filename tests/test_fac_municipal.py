"""Tests for download_fac_municipal — the FAC API-switch for `municipal_finance`.

The live fetch needs egress (api.fac.gov). These tests mock the HTTP layer so
they run fully offline, covering: the municipal name filter, deterministic
parse/sort, the no-egress empty-output path, and that the FAC_API_KEY is sent as
the X-Api-Key header when present.
"""

from __future__ import annotations

import csv
from unittest.mock import MagicMock

import pytest

import scripts.download_fac_municipal as fac_muni
from scripts.download_fac_municipal import (
    OUTPUT_COLUMNS,
    is_municipal,
    parse_records,
    run,
)


@pytest.mark.unit
def test_is_municipal_matches_spanish_and_english_forms():
    assert is_municipal("MUNICIPIO DE PONCE")
    assert is_municipal("Municipality of San Juan")
    assert not is_municipal("UNIVERSITY OF PUERTO RICO")
    assert not is_municipal("PR AQUEDUCT AND SEWER AUTHORITY")
    assert not is_municipal("")


@pytest.mark.unit
def test_parse_records_keeps_only_municipal_and_is_deterministic():
    records = [
        {
            "report_id": "2",
            "auditee_name": "MUNICIPIO DE CAGUAS",
            "audit_year": "2022",
            "auditee_state": "PR",
            "total_amount_expended": "5000000",
        },
        {
            "report_id": "1",
            "auditee_name": "MUNICIPIO DE PONCE",
            "audit_year": "2023",
            "auditee_state": "PR",
            "total_amount_expended": "9000000",
        },
        {
            "report_id": "9",
            "auditee_name": "UNIVERSITY OF PUERTO RICO",
            "audit_year": "2023",
            "auditee_state": "PR",
            "total_amount_expended": "1000000",
        },
    ]
    df = parse_records(records)
    assert list(df.columns) == OUTPUT_COLUMNS
    # Non-municipal auditee dropped; sorted by audit_year desc then name asc.
    assert list(df["auditee_name"]) == ["MUNICIPIO DE PONCE", "MUNICIPIO DE CAGUAS"]
    assert "UNIVERSITY OF PUERTO RICO" not in set(df["auditee_name"])


@pytest.mark.unit
def test_parse_records_municipal_only_false_keeps_all():
    records = [{"auditee_name": "UNIVERSITY OF PUERTO RICO", "audit_year": "2023"}]
    assert len(parse_records(records, municipal_only=False)) == 1
    assert len(parse_records(records, municipal_only=True)) == 0


def _resp(payload):
    r = MagicMock()
    r.status_code = 200
    r.json.return_value = payload
    r.raise_for_status = MagicMock()
    return r


@pytest.mark.unit
def test_run_with_mocked_fac_and_apikey_header(tmp_path, monkeypatch):
    monkeypatch.setenv("FAC_API_KEY", "data-gov-key")
    captured = {}

    def _fake_build_session(user_agent, headers=None):
        captured["headers"] = headers or {}
        session = MagicMock()
        # First page returns one municipal + one non-municipal; second page empty.
        session.get.side_effect = [
            _resp(
                [
                    {
                        "report_id": "1",
                        "auditee_name": "MUNICIPIO DE PONCE",
                        "auditee_state": "PR",
                        "audit_year": "2023",
                        "total_amount_expended": "9000000",
                        "number_of_findings": "2",
                    },
                    {
                        "report_id": "2",
                        "auditee_name": "UNIVERSITY OF PUERTO RICO",
                        "auditee_state": "PR",
                        "audit_year": "2023",
                        "total_amount_expended": "1000000",
                    },
                ]
            ),
            _resp([]),
        ]
        return session

    monkeypatch.setattr(fac_muni, "build_session", _fake_build_session)
    result = run(root=tmp_path, force=True)

    assert result["status"] == "OK"
    assert result["rows"] == 1
    assert captured["headers"].get("X-Api-Key") == "data-gov-key"

    out = tmp_path / "data" / "staging" / "processed" / "pr_municipal_finance.csv"
    with out.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    assert rows[0]["auditee_name"] == "MUNICIPIO DE PONCE"
    assert rows[0]["total_amount_expended"] == "9000000"


@pytest.mark.unit
def test_run_no_egress_writes_empty_without_raising(tmp_path, monkeypatch):
    monkeypatch.delenv("FAC_API_KEY", raising=False)
    monkeypatch.setattr(fac_muni, "build_session", lambda *a, **k: MagicMock())
    # Transport failure surfaces as http_get_json returning None (retries exhausted),
    # so stub it directly to keep the test fast and free of real retry sleeps.
    monkeypatch.setattr(fac_muni, "http_get_json", lambda *a, **k: None)
    result = run(root=tmp_path, force=True)

    assert result["status"] == "NO_DATA"
    assert result["rows"] == 0
    out = tmp_path / "data" / "staging" / "processed" / "pr_municipal_finance.csv"
    with out.open(encoding="utf-8", newline="") as f:
        assert next(csv.reader(f)) == OUTPUT_COLUMNS
