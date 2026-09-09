"""Tests for the ASG supplier-registry scraper (scripts.scrape_asg_suppliers),
plus the ASG tier of scripts.download_active_contractors that now delegates to it.

Covers the pure summary/detail pairing transforms and the pagination + run chain
with the HTTP layer mocked out — no live network calls.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import pytest

from scripts.download_active_contractors import COL_MAP, CONTRACTOR_COLUMNS, ENDPOINTS
from scripts.download_active_contractors import parse_records as parse_contractor_records
from scripts.scrape_asg_suppliers import (
    SUPPLIER_COLUMNS,
    _normalize_row,
    _run,
    declared_page_count,
    fetch_all_records,
    parse_records,
)

FIXTURES = Path(__file__).parent / "fixtures"
SUPPLIERS_HTML = (FIXTURES / "asg_suplidores.html").read_text(encoding="utf-8")


class _NullLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass

    def error(self, *a, **k):
        pass


class _FakeSession:
    def close(self):
        pass


def _row_for(registration_id: str) -> dict:
    """The normalized row for one vendor in the fixture, by Licitador ID."""
    record = next(
        r
        for r in parse_records(SUPPLIERS_HTML)
        if r["summary"]["registration_id"] == registration_id
    )
    return _normalize_row(record["summary"], record["detail"])


# ---------------------------------------------------------------------------
# Unit: pure transforms
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_each_vendor_pairs_its_summary_row_with_its_detail_row():
    records = parse_records(SUPPLIERS_HTML)
    assert len(records) == 2  # two vendors, not the four <tr> elements

    first = records[0]
    assert first["summary"]["registration_id"] == "50727"
    assert first["summary"]["entity_name"] == "10-8 InService"
    assert first["detail"]["municipality"] == "Salinas"
    assert first["detail"]["postal_code"] == "00751"


@pytest.mark.unit
def test_rul_and_rup_values_are_not_mixed():
    # Both sections use identical labels ("Número de Certificado", "Fecha de
    # Vencimiento"), so reading labels document-wide would silently cross them.
    detail = parse_records(SUPPLIERS_HTML)[0]["detail"]
    assert detail["rul"]["Número de Certificado"] == "202563434"
    assert detail["rup"]["Número de Certificado"] == "202562628"
    assert detail["rul"]["Fecha de Vencimiento"] == "2026-12-03"
    assert detail["rup"]["Fecha de Vencimiento"] == "2026-10-31"


@pytest.mark.unit
def test_dates_come_from_the_data_date_attribute():
    # The date spans are empty in the markup — client-side JS formats them — so
    # text_content() is blank and the attribute is the only source.
    detail = parse_records(SUPPLIERS_HTML)[0]["detail"]
    assert detail["rup"]["Fecha de Emisión"] == "2025-10-31"


@pytest.mark.unit
def test_normalize_row_emits_exactly_the_declared_columns():
    record = parse_records(SUPPLIERS_HTML)[0]
    row = _normalize_row(record["summary"], record["detail"])

    assert list(row.keys()) == SUPPLIER_COLUMNS
    assert row["registration_id"] == "50727"
    assert row["entity_normalized"] == "10 8 INSERVICE"
    assert row["contractor_type"] == "RUL+RUP"
    assert row["municipality"] == "Salinas"
    assert row["geo_zip"] == "00751"
    # RUP is preferred over RUL for the registration window.
    assert row["registration_date"] == "2025-10-31"
    assert row["expiry_date"] == "2026-10-31"


@pytest.mark.unit
def test_literal_none_city_does_not_become_a_municipality():
    """ASG interpolates Python's None into the address when the city is missing
    ("None, PR, 00901"). Left alone it enters the registry as a municipality
    named "None"."""
    record = parse_records(SUPPLIERS_HTML)[1]
    row = _normalize_row(record["summary"], record["detail"])

    assert row["municipality"] == ""
    # The postal code is still real, and geo_zip is the first thing geo
    # attribution looks at, so the vendor can still be placed.
    assert row["geo_zip"] == "00901"


@pytest.mark.unit
def test_vendor_in_only_one_registry_reports_only_that_one():
    record = parse_records(SUPPLIERS_HTML)[1]
    row = _normalize_row(record["summary"], record["detail"])

    assert row["contractor_type"] == "RUL"
    # With no RUP block the RUL dates must still come through.
    assert row["registration_date"] == "2025-01-15"
    assert row["expiry_date"] == "2026-01-15"


@pytest.mark.unit
def test_declared_page_count_reads_the_pagination_marker():
    assert declared_page_count(SUPPLIERS_HTML) == 47
    assert declared_page_count("<html><body>no pager</body></html>") is None


@pytest.mark.unit
def test_naics_codes_populate_the_previously_empty_shared_column():
    # naics_code is part of the shared contractor schema and used to be written
    # blank on every row even though ASG publishes classifications for ~99% of
    # vendors.
    row = _row_for("50727")
    assert row["naics_code"] == "238220|61171|92311"


@pytest.mark.unit
def test_naics_descriptions_stay_aligned_when_a_code_has_none():
    """ASG publishes some codes with no description div at all.

    Pairing by position would shift every later description onto the wrong
    code, so an undescribed code has to hold an empty slot instead.
    """
    row = _row_for("50727")
    codes = row["naics_code"].split("|")
    descriptions = row["naics_descriptions"].split("|")

    assert len(codes) == len(descriptions)
    assert descriptions[0] == ""  # 238220 has no description in the source
    assert dict(zip(codes, descriptions)) == {
        "238220": "",
        "61171": "Servicios de Apoyo a la Educación",
        "92311": "Administración de Programas Educativos",
    }


@pytest.mark.unit
def test_vendor_without_a_naics_block_yields_empty_not_an_error():
    row = _row_for("50567")
    assert row["naics_code"] == ""
    assert row["naics_descriptions"] == ""


@pytest.mark.unit
def test_certificates_and_statuses_are_kept_per_registry():
    # Both registries label these identically, so crossing them would silently
    # attribute one registry's certificate to the other.
    row = _row_for("50727")
    assert row["rul_certificate"] == "202563434"
    assert row["rup_certificate"] == "202562628"
    assert row["rul_status"] == "Aprobado"
    assert row["rup_status"] == "Aprobado"


@pytest.mark.unit
def test_contact_details_are_captured():
    row = _row_for("50727")
    assert row["contact_email"] == "info@10-8inservice.org"
    assert row["contact_phone"] == "(866) 496-8108"


@pytest.mark.unit
def test_vendor_listed_in_one_registry_reports_no_certificate_for_the_other():
    row = _row_for("50567")
    assert row["rul_certificate"] == "202511111"
    assert row["rup_certificate"] == ""
    assert row["rul_status"] == "Pendiente"
    assert row["rup_status"] == ""


# ---------------------------------------------------------------------------
# Integration: pagination + run chain (HTTP mocked)
# ---------------------------------------------------------------------------


def _page_html(ids: list[str], total_pages: int | None = 2) -> str:
    rows = "".join(
        f'<tr data-group="{i}"><td>{i}</td><td>Vendor {i}</td><td>Aprobado</td><td>Ver</td></tr>'
        f'<tr class="detail-row" data-group="{i}"><td colspan="4">'
        f'<div class="info-label">Domicilio Fiscal</div>'
        f'<div class="info-value">Calle 1<br>Ponce, PR, 00716</div>'
        f'<div class="info-col"><span class="section-header rul">Información de RUL</span>'
        f'<div class="info-label">RUL Estatus</div><div class="info-value">Aprobado</div>'
        f"</div></td></tr>"
        for i in ids
    )
    pager = f"<span>Página 1 de {total_pages}</span>" if total_pages is not None else ""
    return f"<html><body><table>{rows}</table>{pager}</body></html>"


@pytest.mark.integration
def test_fetch_all_records_walks_to_the_declared_page_count(monkeypatch):
    pages = {1: _page_html(["1", "2"]), 2: _page_html(["3", "4"])}
    calls = []

    def fake_fetch_page(session, page, logger):
        calls.append(page)
        return pages[page]

    monkeypatch.setattr("scripts.scrape_asg_suppliers._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())

    assert calls == [1, 2]
    assert len(records) == 4
    assert truncated is False


@pytest.mark.integration
def test_walk_stops_when_the_server_clamps_to_the_last_page(monkeypatch):
    """?page=999 serves the last page again rather than an empty one, so without
    a repeated-page check the walk cannot terminate."""
    repeated = _page_html(["1"], total_pages=None)
    calls = []

    def fake_fetch_page(session, page, logger):
        calls.append(page)
        return repeated

    monkeypatch.setattr("scripts.scrape_asg_suppliers._fetch_page", fake_fetch_page)
    records, truncated = fetch_all_records(session=None, logger=_NullLogger())

    assert calls == [1, 2]
    assert len(records) == 1


@pytest.mark.integration
def test_run_writes_enriched_rows(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "scripts.scrape_asg_suppliers._fetch_page",
        lambda session, page, logger: SUPPLIERS_HTML if page == 1 else None,
    )
    monkeypatch.setattr(
        "scripts.scrape_asg_suppliers.build_session", lambda *a, **k: _FakeSession()
    )

    result = _run(root=tmp_path, force=True, max_pages=1)
    assert result["status"] == "OK"
    assert result["rows"] == 2

    frame = pd.read_csv(Path(result["path"]), dtype=str)
    # The Licitador ID is the point of this source: it is the asg_licitador_id
    # identifier scheme, so it must survive to the output.
    assert list(frame["registration_id"]) == ["50727", "50567"]
    assert frame.loc[0, "municipality"] == "Salinas"
    assert frame.loc[0, "entity_normalized"] == "10 8 INSERVICE"
    # apply_post_ingest ran, so the geo columns are present and ready to be
    # filled. Resolution itself needs data/reference/pr_municipalities.csv,
    # which does not exist under the tmp_path root used here.
    assert "geo_municipality_name" in frame.columns


# ---------------------------------------------------------------------------
# The download_active_contractors ASG tier
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_no_invented_asg_api_endpoints_remain():
    # /api/suplidores, /suplidores/api/vendors and /suplidores/ were all guesses
    # and all three answer 404. ASG is served by the HTML scraper instead.
    # Compare the parsed host, not a substring: "asg.pr.gov" also matches
    # hostnames that merely contain it (asg.pr.gov.example.com) and paths that
    # mention it, so a substring test both over- and under-reports.
    hosts = {(urlsplit(url).hostname or "").lower() for url in ENDPOINTS}
    assert not {h for h in hosts if h == "asg.pr.gov" or h.endswith(".asg.pr.gov")}


@pytest.mark.unit
def test_col_map_matches_the_headings_asg_actually_renders():
    # None of the previous candidates matched the live headings, so even a
    # successful fetch mapped every column to empty.
    assert "Licitador ID" in COL_MAP["registration_id"]
    assert "Nombre de la Compañía" in COL_MAP["entity_name"]
    assert "Estatus" in COL_MAP["status"]

    raw = pd.DataFrame(
        [
            {
                "Licitador ID": "50727",
                "Nombre de la Compañía": "10-8 InService",
                "Estatus": "Aprobado",
            }
        ]
    )
    mapped = parse_contractor_records(raw, "asg.pr.gov/suplidores")
    assert mapped.loc[0, "registration_id"] == "50727"
    assert mapped.loc[0, "entity_name"] == "10-8 InService"
    assert mapped.loc[0, "status"] == "Aprobado"


@pytest.mark.integration
def test_asg_tier_returns_exactly_the_contractor_schema(monkeypatch):
    from scripts import download_active_contractors as dac

    monkeypatch.setattr(
        "scripts.scrape_asg_suppliers._fetch_page",
        lambda session, page, logger: SUPPLIERS_HTML if page == 1 else None,
    )
    monkeypatch.setattr(
        "scripts.scrape_asg_suppliers.build_session", lambda *a, **k: _FakeSession()
    )

    frame = dac._try_asg_suppliers(_NullLogger())
    # scrape_asg_suppliers carries an extra geo_zip; this module must keep
    # writing exactly CONTRACTOR_COLUMNS.
    assert list(frame.columns) == CONTRACTOR_COLUMNS
    assert len(frame) == 2


@pytest.mark.unit
def test_asg_tier_failure_degrades_to_the_next_tier(monkeypatch):
    from scripts import download_active_contractors as dac

    def boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr("scripts.scrape_asg_suppliers.build_session", boom)

    frame = dac._try_asg_suppliers(_NullLogger())
    assert frame.empty  # logged and skipped, not raised
    assert list(frame.columns) == CONTRACTOR_COLUMNS


# ---------------------------------------------------------------------------
# ASG as a canonical entity + its coverage contract
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_asg_resolves_to_one_canonical_entity_from_every_name_form():
    """ASG appears under a Spanish name, an English translation and two
    acronyms depending on the surface; the default normalizer cannot bridge
    across languages, so the alias layer has to."""
    from moneysweep.runtime.alias_overrides import apply, load_overrides

    overrides = load_overrides()
    canonical = "PUERTO RICO GENERAL SERVICES ADMINISTRATION"
    for form in (
        "ASG",
        "AGS",
        "Administración de Servicios Generales",
        "Administracion de Servicios Generales",
        "General Services Administration",
    ):
        assert apply(form, overrides)[0] == canonical, form


@pytest.mark.unit
def test_asg_is_seeded_as_a_government_agency():
    import csv
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    with (root / "data/reference/agency_master.csv").open() as source_file:
        rows = list(csv.DictReader(source_file))
    asg = next(r for r in rows if r["canonical_name"].endswith("General Services Administration"))
    assert asg["agency_type"] == "government_agency"
    assert asg["jurisdiction"] == "PR"
    assert "ASG" in asg["aliases"]


@pytest.mark.unit
def test_both_asg_sources_have_a_measured_coverage_contract():
    """Without a contract a source is capped at provisional, and a contract with
    a null universe evaluates unverifiable — so the denominators must be real."""
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parent.parent
    contracts = yaml.safe_load((root / "registries/coverage_contracts.yaml").read_text())
    by_id = {c["source_id"]: c for c in contracts["contracts"]}

    for source_id, grain, key in (
        ("asg_emergency_purchases", "contract", "control_number"),
        ("asg_suppliers", "entity", "registration_id"),
    ):
        contract = by_id[source_id]
        assert contract["canonical_grain"] == grain
        assert contract["uniqueness_key"] == [key]
        assert contract["authoritative_universe_method"] == "portal_count"
        assert contract["authoritative_universe_total"] > 0
        assert contract["pagination_required"] is True
