"""Offline tests for scripts/download_sec_officers.py (no network).

Exercises the Form 3/4/5 ownership-XML parsing, the accession-URL builder, and
the seed fallback — the parts where correctness matters. The live EDGAR HTTP
path is monkeypatched.
"""

from __future__ import annotations

import pytest

import scripts.download_sec_officers as S

pytestmark = pytest.mark.unit

FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Sanchez Alejandro M</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>1</isDirector><officerTitle></officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <reportingOwner>
    <reportingOwnerId><rptOwnerName>Doe Jane</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
</ownershipDocument>"""


class _DummySession:
    def close(self):
        pass


def test_parse_owners_extracts_name_title_and_director_flag():
    owners = S._parse_owners(FORM4_XML)
    by_name = {o["officer_name"]: o for o in owners}
    assert by_name["Sanchez Alejandro M"]["is_director"] == "1"
    assert by_name["Sanchez Alejandro M"]["officer_position"] == ""
    assert by_name["Doe Jane"]["officer_position"] == "Chief Financial Officer"
    assert by_name["Doe Jane"]["is_director"] == "0"


def test_parse_owners_tolerates_garbage():
    assert S._parse_owners("<not valid xml") == []
    assert S._parse_owners("<ownershipDocument/>") == []


def test_accession_url_strips_dashes_and_uses_raw_doc():
    url = S._accession_url("0000763901", "0001193125-26-238154", "ownership.xml")
    assert url == "https://www.sec.gov/Archives/edgar/data/763901/000119312526238154/ownership.xml"


def test_run_uses_seed_fallback_when_no_insider_filings(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "_session", lambda: _DummySession())
    # Every submissions lookup returns a company with no recent filings.
    monkeypatch.setattr(
        S, "_get", lambda session, url, params, logger: {"name": "X", "filings": {"recent": {}}}
    )
    result = S.run(root=tmp_path, force=True)
    assert result["status"] == "OK"
    assert result["officers"] == len(S.SEED_OFFICERS)
    out = tmp_path / "data" / "staging" / "processed" / "pr_sec_officers.csv"
    assert out.exists()
    import csv

    rows = list(csv.DictReader(out.open()))
    assert rows and set(rows[0]) == set(S.OFFICER_COLUMNS)
