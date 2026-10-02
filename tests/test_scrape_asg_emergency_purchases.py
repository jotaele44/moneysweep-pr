"""Tests for the ASG emergency-purchase scraper
(scripts.scrape_asg_emergency_purchases).

Covers the pure table/row transforms and the pagination + run chain with the
HTTP layer mocked out — no live network calls.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.scrape_asg_emergency_purchases import (
    EMERGENCY_PURCHASE_COLUMNS,
    _carry_forward_first_seen,
    _normalize_row,
    _run,
    declared_page_count,
    fetch_all_records,
    fiscal_year_and_programme,
    parse_records,
    split_vendor_identity,
)

FIXTURES = Path(__file__).parent / "fixtures"
PURCHASES_HTML = (FIXTURES / "asg_comprasemergencias.html").read_text(encoding="utf-8")


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_records_reads_every_data_row():
    records = parse_records(PURCHASES_HTML)
    assert len(records) == 3
    assert records[0]["Número de Control ASG"] == "26-ASG-EPI-0010"
    assert records[0]["Costo"] == "$70,487.04"


@pytest.mark.unit
def test_parse_records_on_a_page_without_the_table_returns_empty():
    # An ASG error page still answers 200, so "no table" must not raise.
    assert parse_records("<html><body><h1>Error</h1></body></html>") == []




@pytest.mark.unit
def test_source_native_vendor_id_is_extracted_without_name_inference():
    assert split_vendor_identity("Caribbean Composting Inc. (4381)") == (
        "Caribbean Composting Inc. (4381)",
        "Caribbean Composting Inc.",
        "4381",
        "SOURCE_NATIVE_ASG_LICITADOR_ID",
    )
    assert split_vendor_identity("Puerto Rico Wire Products, Inc.") == (
        "Puerto Rico Wire Products, Inc.",
        "Puerto Rico Wire Products, Inc.",
        "",
        "UNRESOLVED_NAME_ONLY",
    )
    assert split_vendor_identity("") == ("", "", "", "UNRESOLVED_MISSING_VENDOR")


@pytest.mark.unit
def test_normalize_preserves_raw_vendor_label_and_source_native_id():
    record = dict(parse_records(PURCHASES_HTML)[0])
    record["Proveedor"] = "A1 Generator Services Incorporated (28546)"
    row = _normalize_row(record)
    assert row["vendor_source_label"] == "A1 Generator Services Incorporated (28546)"
    assert row["vendor_name"] == "A1 Generator Services Incorporated"
    assert row["vendor_registration_id"] == "28546"
    assert row["vendor_identity_scheme"] == "asg_licitador_id"
    assert row["vendor_identity_state"] == "SOURCE_NATIVE_ASG_LICITADOR_ID"

@pytest.mark.unit
def test_normalize_row_emits_exactly_the_declared_columns():
    row = _normalize_row(parse_records(PURCHASES_HTML)[0])
    assert list(row.keys()) == EMERGENCY_PURCHASE_COLUMNS
    assert row["vendor_source_label"] == "Salud Para Todos"
    assert row["vendor_name"] == "Salud Para Todos"
    assert row["vendor_registration_id"] == ""
    assert row["vendor_identity_scheme"] == ""
    assert row["vendor_identity_state"] == "UNRESOLVED_NAME_ONLY"
    assert row["awarding_agency"] == "Departamento de Salud"
    assert row["contract_number"] == "36725"
    # The raw money string is preserved; post_ingest adds the parsed companion.
    assert row["obligation_amount"] == "$70,487.04"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("control_number", "expected"),
    [
        ("26-ASG-EPI-0010", ("2026", "EPI", "Emergencia epidemiológica")),
        ("22-ASG-TTF-296", ("2022", "TTF", "Tormenta Tropical Fiona")),
        ("20-ASG-CV19-765", ("2020", "CV19", "COVID-19")),
    ],
)
def test_fiscal_year_and_programme_covers_every_declared_emergency(control_number, expected):
    # The control number is the only place a row says when it happened — the
    # table renders no date column at all.
    assert fiscal_year_and_programme(control_number) == expected


@pytest.mark.unit
def test_unknown_emergency_code_still_yields_a_fiscal_year():
    # A future emergency must ingest with its year even before it has a label.
    assert fiscal_year_and_programme("27-ASG-XYZ-0001") == ("2027", "XYZ", "")


@pytest.mark.unit
def test_unparseable_control_number_is_blank_not_a_guess():
    assert fiscal_year_and_programme("") == ("", "", "")
    assert fiscal_year_and_programme("not-a-control-number") == ("", "", "")


@pytest.mark.unit
def test_declared_page_count_reads_the_pagination_marker():
    assert declared_page_count(PURCHASES_HTML) == 141
    assert declared_page_count("<html><body>no pager</body></html>") is None


@pytest.mark.unit
def test_creado_rank_records_position_in_the_creation_ordering():
    # ASG renders no date; rank in the -creado ordering is the only ordering
    # signal the page gives, so rows can still be sequenced.
    records = parse_records(PURCHASES_HTML)
    rows = [_normalize_row(r, creado_rank=i) for i, r in enumerate(records, start=1)]
    assert [r["creado_rank"] for r in rows] == ["1", "2", "3"]
    # Omitted rather than guessed when the caller has no ordering context.
    assert _normalize_row(records[0])["creado_rank"] == ""


@pytest.mark.unit
def test_first_seen_at_is_preserved_for_rows_we_have_seen_before(tmp_path):
    """first_seen_at is only an upper bound on the purchase date if it never moves.

    Re-stamping every row each run would turn it into "the date we last
    scraped", which is worse than leaving it blank.
    """
    out_path = tmp_path / "purchases.csv"
    rows = [
        _normalize_row(r, creado_rank=i) for i, r in enumerate(parse_records(PURCHASES_HTML), 1)
    ]

    first = _carry_forward_first_seen(pd.DataFrame(rows), out_path, "2026-01-15")
    first.to_csv(out_path, index=False)
    assert set(first["first_seen_at"]) == {"2026-01-15"}

    # A later run that also picks up a brand-new control number.
    newcomer = {**rows[0], "control_number": "26-ASG-EPI-9999"}
    second = _carry_forward_first_seen(pd.DataFrame([*rows, newcomer]), out_path, "2026-07-27")
    seen = dict(zip(second["control_number"], second["first_seen_at"]))

    assert seen["26-ASG-EPI-0010"] == "2026-01-15"  # kept, not re-stamped
    assert seen["26-ASG-EPI-9999"] == "2026-07-27"  # only the new row is dated


@pytest.mark.unit
def test_first_seen_at_stamps_everything_on_a_first_ever_run(tmp_path):
    rows = [_normalize_row(r) for r in parse_records(PURCHASES_HTML)]
    frame = _carry_forward_first_seen(pd.DataFrame(rows), tmp_path / "absent.csv", "2026-07-27")
    assert set(frame["first_seen_at"]) == {"2026-07-27"}


@pytest.mark.unit
def test_no_transaction_date_is_claimed():
    # The registry notes and the coverage contract both rest on this: ASG
    # publishes no date, so these rows stay at contracts_master grain.
    assert "transaction_date" not in EMERGENCY_PURCHASE_COLUMNS


# ---------------------------------------------------------------------------
# Integration: pagination + run chain (HTTP mocked)
# ---------------------------------------------------------------------------


def _page_html(control_numbers: list[str], total_pages: int | None = 3) -> str:
    rows = "".join(
        f'<tr><td data-title="Número de Control ASG">{cn}</td>'
        f'<td data-title="Número Orden de Compra">PO-{i}</td>'
        f'<td data-title="Bienes o servicios a adquirir">Item {i}</td>'
        f'<td data-title="Proveedor">Vendor {i}</td>'
        f'<td data-title="Costo">$1,000.00</td>'
        f'<td data-title="Agencia">Agencia {i}</td><td></td></tr>'
        for i, cn in enumerate(control_numbers)
    )
    pager = f"<span>Página 1 de {total_pages}</span>" if total_pages is not None else ""
    return f"""<html><body><table id="myTable"><thead><tr class="header">
    <th>Número de Control ASG</th><th>Número Orden de Compra</th>
    <th>Bienes o servicios a adquirir</th><th>Proveedor</th>
    <th>Costo</th><th>Agencia</th><th>x</th></tr></thead>
    <tbody>{rows}</tbody></table>
    {pager}</body></html>"""


@pytest.mark.integration
def test_fetch_all_records_walks_to_the_declared_page_count(monkeypatch):
    pages = {
        1: _page_html(["20-ASG-CV19-1", "20-ASG-CV19-2"]),
        2: _page_html(["20-ASG-CV19-3", "20-ASG-CV19-4"]),
        3: _page_html(["20-ASG-CV19-5"]),
    }
    calls = []

    def fake_fetch_page(session, page, logger):
        calls.append(page)
        return pages[page]

    monkeypatch.setattr("scripts.scrape_asg_emergency_purchases._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())

    assert calls == [1, 2, 3]  # stops at the declared total, does not try page 4
    assert len(records) == 5
    assert truncated is False


@pytest.mark.integration
def test_walk_stops_when_the_server_clamps_to_the_last_page(monkeypatch):
    """Requesting a page past the end serves the LAST page again rather than an
    empty one, so without a repeated-page check the walk cannot terminate."""
    repeated = _page_html(["22-ASG-TTF-1"], total_pages=None)  # no page marker at all
    calls = []

    def fake_fetch_page(session, page, logger):
        calls.append(page)
        return repeated

    monkeypatch.setattr("scripts.scrape_asg_emergency_purchases._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())

    assert calls == [1, 2]  # second page repeats the first, so the walk stops
    assert len(records) == 1
    assert truncated is False


@pytest.mark.integration
def test_a_failed_page_marks_the_result_truncated(monkeypatch):
    def fake_fetch_page(session, page, logger):
        return _page_html(["26-ASG-EPI-1"]) if page == 1 else None

    monkeypatch.setattr("scripts.scrape_asg_emergency_purchases._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())

    assert len(records) == 1
    assert truncated is True  # a partial pull must not read as a clean finish


@pytest.mark.integration
def test_run_writes_enriched_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.scrape_asg_emergency_purchases._fetch_page",
        lambda session, page, logger: PURCHASES_HTML if page == 1 else None,
    )
    monkeypatch.setattr(
        "scripts.scrape_asg_emergency_purchases.build_session", lambda *a, **k: _FakeSession()
    )

    result = _run(root=tmp_path, force=True, max_pages=1)
    assert result["status"] == "OK"
    assert result["rows"] == 3

    frame = pd.read_csv(Path(result["path"]), dtype=str)
    assert list(frame["control_number"]) == [
        "26-ASG-EPI-0010",
        "22-ASG-TTF-296",
        "20-ASG-CV19-765",
    ]
    # apply_post_ingest turns the formatted money string into a real number and
    # normalizes the vendor, which is what makes these rows joinable.
    assert float(frame.loc[1, "obligation_amount_canonical"]) == 643500.0
    assert frame.loc[0, "entity_normalized"] == "SALUD PARA TODOS"
    assert list(frame["fiscal_year"]) == ["2026", "2022", "2020"]


@pytest.mark.integration
def test_run_on_an_empty_scrape_writes_headers_and_reports_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.scrape_asg_emergency_purchases._fetch_page",
        lambda session, page, logger: None,
    )
    monkeypatch.setattr(
        "scripts.scrape_asg_emergency_purchases.build_session", lambda *a, **k: _FakeSession()
    )

    result = _run(root=tmp_path, force=True)
    assert result["status"] == "ERROR"
    assert result["rows"] == 0
    assert result["errors"]
    # The output still exists with its header row, so downstream steps read an
    # empty table rather than a missing file.
    frame = pd.read_csv(Path(result["path"]))
    assert list(frame.columns) == EMERGENCY_PURCHASE_COLUMNS
    assert frame.empty


class _FakeSession:
    def close(self):
        pass
