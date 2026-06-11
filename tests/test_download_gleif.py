"""Offline tests for scripts/download_gleif.py (no network).

Exercises the pure GLEIF→schema mapping and the PR filter union/de-dupe, which
are the parts where correctness matters. The live HTTP path is monkeypatched.
"""
from __future__ import annotations

import pytest

import scripts.download_gleif as G

pytestmark = pytest.mark.unit


class _DummyLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


def _rec(lei: str) -> dict:
    return {"attributes": {"lei": lei, "entity": {"legalName": {"name": f"Entity {lei}"}}}}


def test_fmt_address_joins_parts_and_handles_none():
    addr = {"addressLines": ["1250 Ave. Ponce de Leon", "Suite 301"],
            "city": "San Juan", "postalCode": "00907", "country": "PR"}
    out = G._fmt_address(addr)
    assert "1250 Ave. Ponce de Leon" in out and "San Juan" in out and "PR" in out
    assert G._fmt_address(None) == ""
    assert G._fmt_address({}) == ""


def test_map_entity_maps_canonical_fields():
    rec = {"attributes": {"lei": "254900MBF636B6XXXE69", "entity": {
        "legalName": {"name": "FP Strategies LLC"},
        "otherNames": [{"name": "FPS"}],
        "jurisdiction": "PR",
        "legalForm": {"id": "35RF"},
        "status": "ACTIVE",
        "registeredAs": "556123",
        "legalAddress": {"addressLines": ["X St"], "city": "San Juan", "country": "PR"},
        "headquartersAddress": {"city": "San Juan", "country": "PR"},
        "creationDate": "2025-06-16T00:00:00Z",
    }}}
    row = G._map_entity(rec)
    assert row["lei"] == "254900MBF636B6XXXE69"
    assert row["legal_name"] == "FP Strategies LLC"
    assert row["other_names"] == "FPS"
    assert row["jurisdiction"] == "PR"
    assert row["legal_form"] == "35RF"
    assert row["entity_status"] == "ACTIVE"
    assert row["registered_as"] == "556123"
    assert "San Juan" in row["legal_address"]
    assert row["registration_date"] == "2025-06-16T00:00:00Z"
    assert row["source_url"].endswith("254900MBF636B6XXXE69")
    assert set(row) == set(G.ENTITY_COLUMNS)


def test_fetch_entities_unions_both_filters_and_dedupes(monkeypatch):
    # Country filter returns AAA, BBB; jurisdiction filter returns BBB, CCC.
    # BBB overlaps and must be de-duped (guards the documented undercount union).
    def fake_get(session, url, params, **kw):
        if "filter[entity.legalAddress.country]" in params:
            return {"data": [_rec("AAA"), _rec("BBB")], "meta": {"pagination": {"lastPage": 1}}}
        return {"data": [_rec("BBB"), _rec("CCC")], "meta": {"pagination": {"lastPage": 1}}}

    monkeypatch.setattr(G, "http_get_json", fake_get)
    rows = G._fetch_entities(session=None, logger=_DummyLogger())
    assert sorted(r["lei"] for r in rows) == ["AAA", "BBB", "CCC"]


def test_fetch_entities_paginates_until_last_page(monkeypatch):
    def fake_get(session, url, params, **kw):
        if "filter[entity.jurisdiction]" in params:  # second filter: empty
            return {"data": [], "meta": {"pagination": {"lastPage": 1}}}
        page = params["page[number]"]
        return {"data": [_rec(f"P{page}")], "meta": {"pagination": {"lastPage": 2}}}

    monkeypatch.setattr(G, "http_get_json", fake_get)
    rows = G._fetch_entities(session=None, logger=_DummyLogger())
    assert sorted(r["lei"] for r in rows) == ["P1", "P2"]
