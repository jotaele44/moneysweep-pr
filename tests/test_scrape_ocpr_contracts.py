"""Tests for the OCPR contract-registry scraper
(scripts.scrape_ocpr_contracts).

Covers the pure record-mapping transforms and the paginate/run chain with the
HTTP layer mocked out — no live network calls.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.ingest_ocpr_contracts import OUTPUT_COLUMNS
from scripts.scrape_ocpr_contracts import (
    _cached_row_count,
    _extract_document_url,
    _fetch_page,
    _normalize_row,
    _parse_dotnet_date,
    fetch_all_records,
    main,
    _run,
)

# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_dotnet_date_extracts_iso_date():
    assert _parse_dotnet_date("/Date(1260507600000)/") == "2009-12-11"
    assert _parse_dotnet_date(None) == ""
    assert _parse_dotnet_date("") == ""
    assert _parse_dotnet_date("not a date") == ""


@pytest.mark.unit
def test_parse_dotnet_date_handles_timezone_offset_suffix():
    # Same instant as the bare form above, with a trailing offset some
    # DateTimeOffset fields emit.
    assert _parse_dotnet_date("/Date(1260507600000-0400)/") == "2009-12-11"


@pytest.mark.unit
def test_extract_document_url_resolves_when_present():
    record = {"DocumentWithoutSocialSecurityId": "abc-123"}
    assert (
        _extract_document_url(record)
        == "https://consultacontratos.ocpr.gov.pr/contract/downloaddocument?code=abc-123"
    )


@pytest.mark.unit
def test_extract_document_url_blank_when_absent():
    assert _extract_document_url({}) == ""
    assert _extract_document_url({"DocumentWithoutSocialSecurityId": None}) == ""


@pytest.mark.unit
def test_normalize_row_maps_api_record_to_canonical_schema():
    record = {
        "ContractNumber": "010-00-0280",
        "EntityId": 4027,
        "EntityName": "Municipio de Fajardo",
        "AmountToPay": 535000.0,
        "AmountToReceive": None,
        "EffectiveDateFrom": "/Date(1260507600000)/",
        "EffectiveDateTo": "/Date(1260507600000)/",
        "Service": "COMPRA DE INMUEBLES",
        "ServiceGroup": "COMPRA, VENTA, ALQUILER Y/O DESARROLLO DE INMUEBLES",
        "CancellationDate": None,
        "DocumentWithoutSocialSecurityId": "0ba3f165-ddb6-45d8-b313-184fb6b78534",
        "Contractors": [{"Name": "WESTERNBANK PUERTO RICO", "SocialSecurity": None}],
    }
    row = _normalize_row(record)
    assert list(row.keys()) == OUTPUT_COLUMNS
    assert row["contract_number"] == "010-00-0280"
    assert row["contractor_name"] == "WESTERNBANK PUERTO RICO"
    assert row["contractor_id"] == ""
    assert row["agency"] == "Municipio de Fajardo"
    assert row["contract_amount"] == "535000.0"
    assert row["start_date"] == "2009-12-11"
    assert row["end_date"] == "2009-12-11"
    assert row["service_description"] == "COMPRA DE INMUEBLES"
    assert row["status"] == ""
    assert (
        row["document_url"]
        == "https://consultacontratos.ocpr.gov.pr/contract/downloaddocument?code=0ba3f165-ddb6-45d8-b313-184fb6b78534"
    )


@pytest.mark.unit
def test_normalize_row_joins_multiple_contractors():
    record = {
        "ContractNumber": "X-1",
        "Contractors": [{"Name": "ACME CORP"}, {"Name": "BETA LLC"}],
    }
    row = _normalize_row(record)
    assert row["contractor_name"] == "ACME CORP; BETA LLC"


@pytest.mark.unit
def test_normalize_row_marks_cancelled_status():
    record = {"ContractNumber": "X-2", "CancellationDate": "/Date(1600000000000)/"}
    row = _normalize_row(record)
    assert row["status"] == "Cancelado"


@pytest.mark.unit
def test_normalize_row_amount_blank_when_amount_to_pay_missing():
    # AmountToReceive exists in the raw API schema but real samples never
    # populated it — no speculative fallback to it, just leave blank.
    record = {"ContractNumber": "X-3", "AmountToPay": None, "AmountToReceive": 42.0}
    row = _normalize_row(record)
    assert row["contract_amount"] == ""


@pytest.mark.unit
def test_normalize_row_agency_blank_when_entity_name_missing():
    record = {"ContractNumber": "X-4", "EntityId": 999, "EntityName": None}
    row = _normalize_row(record)
    assert row["agency"] == ""


@pytest.mark.unit
def test_normalize_row_raises_on_malformed_contractors_shape():
    """_normalize_row itself doesn't swallow bad input — resilience is the
    caller's job (fetch_all_records skips and logs per-record failures)."""
    record = {"ContractNumber": "X-5", "Contractors": "not-a-list"}
    with pytest.raises(AttributeError):
        _normalize_row(record)


# ---------------------------------------------------------------------------
# Unit: cache-check row counting
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_cached_row_count_counts_data_rows_only(tmp_path: Path):
    path = tmp_path / "cached.csv"
    path.write_text("a,b\n1,2\n3,4\n5,6\n", encoding="utf-8")
    assert _cached_row_count(path) == 3


# ---------------------------------------------------------------------------
# Unit: _fetch_page HTTP status / response handling (session.post mocked)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text="", json_ok=True):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text
        self._json_ok = json_ok

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        if not self._json_ok:
            # Matches real requests behavior (>=2.27): a non-JSON body raises
            # JSONDecodeError, itself a RequestException subclass.
            raise requests.exceptions.JSONDecodeError("Expecting value", "", 0)
        return self._payload


class _FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def post(self, *a, **k):
        self.calls += 1
        return self._responses[self.calls - 1]


@pytest.mark.unit
def test_fetch_page_retries_after_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("scripts.scrape_ocpr_contracts.time.sleep", lambda s: None)
    session = _FakeSession(
        [
            _FakeResponse(status_code=429),
            _FakeResponse(status_code=200, payload={"recordsTotal": 1, "data": []}),
        ]
    )
    result = _fetch_page(session, token="tok", start=0, length=100, logger=_NullLogger())
    assert result == {"recordsTotal": 1, "data": []}
    assert session.calls == 2


@pytest.mark.unit
def test_fetch_page_terminal_4xx_does_not_retry(monkeypatch):
    monkeypatch.setattr("scripts.scrape_ocpr_contracts.time.sleep", lambda s: None)
    session = _FakeSession([_FakeResponse(status_code=400, text="bad request")])
    result = _fetch_page(session, token="tok", start=0, length=100, logger=_NullLogger())
    assert result is None
    assert session.calls == 1


@pytest.mark.unit
def test_fetch_page_retries_on_non_json_200_then_gives_up(monkeypatch):
    """A redirect-turned-200 (e.g. bounced back to the HTML search page) must
    not crash the scrape — resp.json()'s JSONDecodeError is already a
    requests.RequestException subclass, so it retries like any other
    transient failure and eventually surfaces as a clean page failure."""
    monkeypatch.setattr("scripts.scrape_ocpr_contracts.time.sleep", lambda s: None)
    session = _FakeSession([_FakeResponse(status_code=200, json_ok=False)] * 3)
    result = _fetch_page(session, token="tok", start=0, length=100, logger=_NullLogger())
    assert result is None
    assert session.calls == 3  # exhausted RETRY_POLICY.max_attempts, no crash


# ---------------------------------------------------------------------------
# Integration: pagination + full run chain (HTTP mocked)
# ---------------------------------------------------------------------------


def _fake_record(num):
    return {
        "ContractNumber": f"C-{num}",
        "EntityId": num,
        "EntityName": f"Agency {num}",
        "AmountToPay": 100.0,
        "EffectiveDateFrom": "/Date(1260507600000)/",
        "EffectiveDateTo": "/Date(1260507600000)/",
        "Contractors": [{"Name": f"Contractor {num}"}],
    }


@pytest.mark.integration
def test_fetch_all_records_paginates_until_records_total(monkeypatch):
    pages = [
        {"recordsTotal": 25, "data": [_fake_record(i) for i in range(10)]},
        {"recordsTotal": 25, "data": [_fake_record(i) for i in range(10, 20)]},
        {"recordsTotal": 25, "data": [_fake_record(i) for i in range(20, 25)]},
    ]
    calls = []

    def fake_fetch_page(session, token, start, length, logger):
        calls.append(start)
        return pages[len(calls) - 1]

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    rows, truncated = fetch_all_records(
        session=None, token="tok", logger=_NullLogger(), page_length=10
    )
    assert len(rows) == 25
    assert {r["contract_number"] for r in rows} == {f"C-{i}" for i in range(25)}
    assert calls == [0, 10, 20]
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_handles_null_records_total_without_crashing(monkeypatch):
    def fake_fetch_page(session, token, start, length, logger):
        return {"recordsTotal": None, "data": []}

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    rows, truncated = fetch_all_records(session=None, token="tok", logger=_NullLogger())
    assert rows == []
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_respects_max_pages(monkeypatch):
    def fake_fetch_page(session, token, start, length, logger):
        return {"recordsTotal": 100000, "data": [_fake_record(start)]}

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    rows, truncated = fetch_all_records(
        session=None, token="tok", logger=_NullLogger(), page_length=1, max_pages=2
    )
    assert len(rows) == 2
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_flags_truncated_when_reauth_also_fails(monkeypatch):
    def fake_fetch_page(session, token, start, length, logger):
        return None

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts._session_and_token",
        lambda logger: (requests.Session(), "fresh-tok"),
    )
    rows, truncated = fetch_all_records(session=None, token="tok", logger=_NullLogger())
    assert rows == []
    assert truncated is True


@pytest.mark.integration
def test_fetch_all_records_recovers_via_reauth_after_one_failed_page(monkeypatch):
    """A page failure gets one re-authenticate-and-retry before giving up —
    simulates a stale token mid-run recovering on the next attempt."""
    attempts = {"n": 0}

    def fake_fetch_page(session, token, start, length, logger):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return None  # first attempt fails (e.g. stale token)
        return {"recordsTotal": 1, "data": [_fake_record(1)]}

    reauth_calls = []

    def fake_session_and_token(logger):
        reauth_calls.append(True)
        return requests.Session(), "fresh-tok"

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    monkeypatch.setattr("scripts.scrape_ocpr_contracts._session_and_token", fake_session_and_token)
    rows, truncated = fetch_all_records(session=None, token="stale-tok", logger=_NullLogger())
    assert len(reauth_calls) == 1
    assert len(rows) == 1
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_truncates_when_reauth_itself_raises(monkeypatch):
    def fake_fetch_page(session, token, start, length, logger):
        return None

    def _boom(logger):
        raise RuntimeError("token page unreachable")

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    monkeypatch.setattr("scripts.scrape_ocpr_contracts._session_and_token", _boom)
    rows, truncated = fetch_all_records(session=None, token="tok", logger=_NullLogger())
    assert rows == []
    assert truncated is True


@pytest.mark.integration
def test_fetch_all_records_skips_malformed_record_and_continues(monkeypatch):
    good = _fake_record(1)
    bad = {"ContractNumber": "BAD-1", "Contractors": "not-a-list"}

    def fake_fetch_page(session, token, start, length, logger):
        return {"recordsTotal": 2, "data": [good, bad]}

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._fetch_page", fake_fetch_page)
    rows, truncated = fetch_all_records(
        session=None, token="tok", logger=_NullLogger(), max_pages=1
    )
    assert len(rows) == 1
    assert rows[0]["contract_number"] == "C-1"
    assert truncated is False  # a malformed record is not a page-fetch failure


@pytest.mark.integration
def test_run_materializes_processed_csv_from_scraped_records(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts._session_and_token",
        lambda logger: (requests.Session(), "tok"),
    )
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts.fetch_all_records",
        lambda session, token, logger, page_length=100, max_pages=None: (
            [_normalize_row(_fake_record(1)), _normalize_row(_fake_record(2))],
            False,
        ),
    )
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 2
    assert result["errors"] == []
    assert result["status"] == "OK"

    out_path = tmp_path / "data" / "staging" / "processed" / "pr_ocpr_contracts.csv"
    assert out_path.exists()
    with out_path.open(encoding="utf-8") as source_file:
        rows = list(csv.DictReader(source_file))
    assert list(rows[0].keys()) == OUTPUT_COLUMNS
    assert {r["contract_number"] for r in rows} == {"C-1", "C-2"}


@pytest.mark.integration
def test_run_reports_error_when_scrape_was_truncated(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts._session_and_token",
        lambda logger: (requests.Session(), "tok"),
    )
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts.fetch_all_records",
        lambda session, token, logger, page_length=100, max_pages=None: (
            [_normalize_row(_fake_record(1))],
            True,
        ),
    )
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 1
    assert result["errors"], "a truncated scrape must surface an error even though rows > 0"
    assert result["status"] == "TRUNCATED"


@pytest.mark.integration
def test_run_with_no_records_writes_empty_header_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts._session_and_token",
        lambda logger: (requests.Session(), "tok"),
    )
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts.fetch_all_records",
        lambda session, token, logger, page_length=100, max_pages=None: ([], False),
    )
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0
    assert result["status"] == "ERROR"
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_ocpr_contracts.csv"
    assert out_path.exists()
    with out_path.open(encoding="utf-8") as source_file:
        assert list(csv.DictReader(source_file)) == []


@pytest.mark.integration
def test_run_skips_scrape_when_cached_output_exists(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_ocpr_contracts.csv"
    out_path.parent.mkdir(parents=True)
    pd.DataFrame([_normalize_row(_fake_record(1))]).to_csv(out_path, index=False)

    def _boom(*a, **k):
        raise AssertionError("_session_and_token should not be called when cached")

    monkeypatch.setattr("scripts.scrape_ocpr_contracts._session_and_token", _boom)
    result = _run(root=tmp_path, force=False)
    assert result["rows"] == 1
    assert result["status"] == "OK"


@pytest.mark.integration
def test_main_exit_code_reflects_truncation_even_with_rows(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts._run",
        lambda force, max_pages, page_length: {
            "rows": 1,
            "path": "x",
            "errors": ["truncated"],
            "status": "TRUNCATED",
        },
    )
    monkeypatch.setattr("sys.argv", ["scrape_ocpr_contracts.py"])
    assert main() == 1


@pytest.mark.integration
def test_main_exit_code_zero_on_clean_run(monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_ocpr_contracts._run",
        lambda force, max_pages, page_length: {
            "rows": 5,
            "path": "x",
            "errors": [],
            "status": "OK",
        },
    )
    monkeypatch.setattr("sys.argv", ["scrape_ocpr_contracts.py"])
    assert main() == 0


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass
