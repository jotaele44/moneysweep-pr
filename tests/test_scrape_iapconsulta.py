"""Tests for the iapconsulta.ocpr.gov.pr audit/investigation scraper
(scripts.scrape_iapconsulta).

Covers the pure record-mapping transforms and the paginate/run chain with the
HTTP layer mocked out — no live network calls.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pandas as pd
import pytest
import requests

from scripts.ingest_contralor import CONTRALOR_COLUMNS
from scripts.scrape_iapconsulta import (
    _extract_report_url,
    _fetch_page,
    _normalize_row,
    _year_from_date,
    fetch_all_records,
    _run,
)

# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_extract_report_url_resolves_relative_href():
    html = (
        '<a href="../../OpenDoc.aspx?id=abc-123&nombre=DA-08-08" target="_blank">'
        '<i class="fa fa-search"></i></a></td>'
    )
    assert (
        _extract_report_url(html)
        == "https://iapconsulta.ocpr.gov.pr/OpenDoc.aspx?id=abc-123&nombre=DA-08-08"
    )


@pytest.mark.unit
def test_extract_report_url_handles_missing_or_blank():
    assert _extract_report_url(None) == ""
    assert _extract_report_url("") == ""
    assert _extract_report_url('<i class="fa fa-book"></i>') == ""


@pytest.mark.unit
def test_year_from_date_extracts_four_digit_year():
    assert _year_from_date("4/12/2010 12:00:00 AM") == "2010"
    assert _year_from_date("") == ""
    assert _year_from_date(None) == ""


@pytest.mark.unit
def test_normalize_row_maps_api_record_to_canonical_schema():
    record = {
        "NumInforme": "DA-08-08",
        "NombreInforme": "CUERPO DE BOMBEROS DE PUERTO RICO",
        "TipoInforme": "REGULAR",
        "Entidad": "CUERPO DE BOMBEROS DE PUERTO RICO",
        "Rama": "EJECUTIVA",
        "Publicacion": "2/13/2008 12:00:00 AM",
        "Open": '<a href="../../OpenDoc.aspx?id=xyz&nombre=DA-08-08"></a>',
    }
    row = _normalize_row(record)
    assert list(row.keys()) == CONTRALOR_COLUMNS
    assert row["entity_name"] == "CUERPO DE BOMBEROS DE PUERTO RICO"
    assert row["audit_id"] == "DA-08-08"
    assert row["audit_type"] == "REGULAR"
    assert row["audit_year"] == "2008"
    assert row["branch"] == "EJECUTIVA"
    assert (
        row["report_url"] == "https://iapconsulta.ocpr.gov.pr/OpenDoc.aspx?id=xyz&nombre=DA-08-08"
    )


@pytest.mark.unit
def test_normalize_row_captures_investigations_report_type():
    record = {
        "NumInforme": "RIQ-DIE-23-03",
        "NombreInforme": "MUNICIPIO DE SAN LORENZO",
        "TipoInforme": "INVESTIGACIONES",
        "Entidad": "MUNICIPIO DE SAN LORENZO",
        "Rama": "MUNICIPIO",
        "Publicacion": "1/5/2023 12:00:00 AM",
        "Open": "",
    }
    row = _normalize_row(record)
    assert row["audit_type"] == "INVESTIGACIONES"
    assert row["report_url"] == ""


@pytest.mark.unit
def test_normalize_row_falls_back_to_report_title_when_entity_is_na():
    record = {
        "NumInforme": "DE-08-68",
        "NombreInforme": "DEPARTAMENTO DE EDUCACIÓN DISTRITO ESCOLAR DE AGUADA",
        "TipoInforme": "ESPECIAL",
        "Entidad": "N/A",
        "Rama": "N/A",
        "Publicacion": "2/11/2008 12:00:00 AM",
        "Open": "",
    }
    row = _normalize_row(record)
    assert row["entity_name"] == "DEPARTAMENTO DE EDUCACIÓN DISTRITO ESCOLAR DE AGUADA"
    assert row["entity_normalized"] == "DEPARTAMENTO DE EDUCACIÓN DISTRITO ESCOLAR DE AGUADA"


# ---------------------------------------------------------------------------
# Unit: _fetch_page HTTP status handling (session.post mocked)
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
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
    monkeypatch.setattr("scripts.scrape_iapconsulta.time.sleep", lambda s: None)
    session = _FakeSession(
        [
            _FakeResponse(status_code=429),
            _FakeResponse(status_code=200, payload={"recordsTotal": 1, "data": []}),
        ]
    )
    result = _fetch_page(session, start=0, logger=_NullLogger())
    assert result == {"recordsTotal": 1, "data": []}
    assert session.calls == 2


@pytest.mark.unit
def test_fetch_page_terminal_4xx_does_not_retry(monkeypatch):
    monkeypatch.setattr("scripts.scrape_iapconsulta.time.sleep", lambda s: None)
    session = _FakeSession([_FakeResponse(status_code=400, text="bad request")])
    result = _fetch_page(session, start=0, logger=_NullLogger())
    assert result is None
    assert session.calls == 1  # no retry burned on a non-429 4xx


# ---------------------------------------------------------------------------
# Integration: pagination + full run chain (HTTP mocked)
# ---------------------------------------------------------------------------


def _fake_record(num):
    return {
        "NumInforme": f"M-{num}",
        "NombreInforme": f"ENTIDAD {num}",
        "TipoInforme": "REGULAR",
        "Entidad": f"ENTIDAD {num}",
        "Rama": "EJECUTIVA",
        "Publicacion": "1/1/2020 12:00:00 AM",
        "Open": "",
    }


@pytest.mark.integration
def test_fetch_all_records_paginates_until_records_total(monkeypatch):
    pages = [
        {"recordsTotal": 25, "data": [_fake_record(i) for i in range(10)]},
        {"recordsTotal": 25, "data": [_fake_record(i) for i in range(10, 20)]},
        {"recordsTotal": 25, "data": [_fake_record(i) for i in range(20, 25)]},
    ]
    calls = []

    def fake_fetch_page(session, start, logger):
        calls.append(start)
        return pages[len(calls) - 1]

    monkeypatch.setattr("scripts.scrape_iapconsulta._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())
    assert len(records) == 25
    assert calls == [0, 10, 20]
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_advances_by_actual_batch_length_not_assumed_page_size(monkeypatch):
    """If the server ever returns a batch shorter than PAGE_SIZE mid-scan, the
    next `start` must follow the real batch length so no records are skipped."""
    pages = [
        {"recordsTotal": 13, "data": [_fake_record(i) for i in range(7)]},  # short first batch
        {"recordsTotal": 13, "data": [_fake_record(i) for i in range(7, 13)]},
    ]
    calls = []

    def fake_fetch_page(session, start, logger):
        calls.append(start)
        return pages[len(calls) - 1]

    monkeypatch.setattr("scripts.scrape_iapconsulta._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())
    assert len(records) == 13
    assert calls == [0, 7]
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_handles_null_records_total_without_crashing(monkeypatch):
    def fake_fetch_page(session, start, logger):
        return {"recordsTotal": None, "data": []}

    monkeypatch.setattr("scripts.scrape_iapconsulta._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())
    assert records == []
    assert truncated is False


@pytest.mark.integration
def test_fetch_all_records_respects_max_pages(monkeypatch):
    def fake_fetch_page(session, start, logger):
        return {"recordsTotal": 1000, "data": [_fake_record(start)]}

    monkeypatch.setattr("scripts.scrape_iapconsulta._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger(), max_pages=2)
    assert len(records) == 2
    assert truncated is False  # intentional cutoff, not a failure


@pytest.mark.integration
def test_fetch_all_records_flags_truncated_on_failed_page(monkeypatch):
    def fake_fetch_page(session, start, logger):
        return None

    monkeypatch.setattr("scripts.scrape_iapconsulta._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())
    assert records == []
    assert truncated is True


@pytest.mark.integration
def test_run_materializes_processed_csv_from_scraped_records(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_iapconsulta.fetch_all_records",
        lambda session, logger, max_pages=None: ([_fake_record(1), _fake_record(2)], False),
    )
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 2
    assert result["errors"] == []

    out_path = tmp_path / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    assert out_path.exists()
    with out_path.open(encoding="utf-8") as source_file:
        rows = list(csv.DictReader(source_file))
    assert list(rows[0].keys()) == CONTRALOR_COLUMNS
    assert {r["entity_name"] for r in rows} == {"ENTIDAD 1", "ENTIDAD 2"}


@pytest.mark.integration
def test_run_reports_error_when_scrape_was_truncated(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_iapconsulta.fetch_all_records",
        lambda session, logger, max_pages=None: ([_fake_record(1)], True),
    )
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 1
    assert result["errors"], "a truncated scrape must surface an error even though rows > 0"


@pytest.mark.integration
def test_run_with_no_records_writes_empty_header_only(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        "scripts.scrape_iapconsulta.fetch_all_records",
        lambda session, logger, max_pages=None: ([], False),
    )
    result = _run(root=tmp_path, force=True)
    assert result["rows"] == 0
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    assert out_path.exists()
    with out_path.open(encoding="utf-8") as source_file:
        assert list(csv.DictReader(source_file)) == []


@pytest.mark.integration
def test_run_skips_scrape_when_cached_output_exists(tmp_path: Path, monkeypatch):
    out_path = tmp_path / "data" / "staging" / "processed" / "pr_contralor_audits.csv"
    out_path.parent.mkdir(parents=True)
    pd.DataFrame([_normalize_row(_fake_record(1))]).to_csv(out_path, index=False)

    def _boom(*a, **k):
        raise AssertionError("fetch_all_records should not be called when cached")

    monkeypatch.setattr("scripts.scrape_iapconsulta.fetch_all_records", _boom)
    result = _run(root=tmp_path, force=False)
    assert result["rows"] == 1


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass
