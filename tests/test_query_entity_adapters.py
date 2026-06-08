"""Tests for the entity-mode source adapters (SAM, OFAC SDN)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from contract_sweeper.query.adapters.ofac import OFACSDNAdapter, parse_sdn_xml
from contract_sweeper.query.adapters.sam import (
    PARAM_FOR_KIND,
    SAMEntitiesAdapter,
)
from contract_sweeper.query.entity_types import EntityIdentifier, EntityQuery
from contract_sweeper.query.types import CredentialMissing

REPO_ROOT = Path(__file__).resolve().parents[1]


def _mock_response(payload):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload
    resp.content = payload if isinstance(payload, (bytes, bytearray)) else b""
    resp.raise_for_status = MagicMock()
    return resp


def _sam_payload(uei: str, name: str, state: str = "PR") -> dict:
    return {
        "entityData": [
            {
                "entityRegistration": {
                    "ueiSAM": uei,
                    "cageCode": "12345",
                    "legalBusinessName": name,
                    "registrationStatus": "Active",
                    "registrationExpirationDate": "2027-01-01",
                },
                "coreData": {
                    "physicalAddress": {"stateOrProvinceCode": state, "city": "San Juan"},
                    "entityHierarchyInformation": {
                        "immediateParentEntity": {
                            "ueiSAM": "PARENT1",
                            "legalBusinessName": "Parent Co",
                        },
                    },
                },
            }
        ]
    }


# ---------------------------------------------------------------------------
# SAM
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_sam_raises_credential_missing_before_http_call(monkeypatch):
    monkeypatch.delenv("SAM_API_KEY", raising=False)
    session = MagicMock()
    adapter = SAMEntitiesAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="X"),))
    with pytest.raises(CredentialMissing) as exc:
        adapter.fetch(eq)
    assert exc.value.env_var == "SAM_API_KEY"
    session.get.assert_not_called()


@pytest.mark.unit
def test_sam_routes_uei_kind_to_ueisam_param(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "test-key")
    session = MagicMock()
    session.get.return_value = _mock_response(_sam_payload("QY9NQ", "LUMA"))
    adapter = SAMEntitiesAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="QY9NQ"),))
    df = adapter.fetch(eq)
    assert len(df) == 1
    params = session.get.call_args.kwargs.get("params") or session.get.call_args[1]["params"]
    assert params["ueiSAM"] == "QY9NQ"
    assert params["api_key"] == "test-key"
    assert params["registrationStatus"] == "A"
    assert PARAM_FOR_KIND["uei"] == "ueiSAM"


@pytest.mark.unit
def test_sam_routes_name_kind_to_legalbusinessname_param(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "test-key")
    session = MagicMock()
    session.get.return_value = _mock_response(_sam_payload("X1", "Acme"))
    adapter = SAMEntitiesAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="name", value="Acme Corp"),))
    adapter.fetch(eq)
    params = session.get.call_args.kwargs.get("params") or session.get.call_args[1]["params"]
    assert params["legalBusinessName"] == "Acme Corp"
    assert "ueiSAM" not in params


@pytest.mark.unit
def test_sam_routes_cage_kind_to_cagecode_param(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "test-key")
    session = MagicMock()
    session.get.return_value = _mock_response(_sam_payload("X1", "Acme"))
    adapter = SAMEntitiesAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="cage", value="ABCDE"),))
    adapter.fetch(eq)
    params = session.get.call_args.kwargs.get("params") or session.get.call_args[1]["params"]
    assert params["cageCode"] == "ABCDE"


@pytest.mark.unit
def test_sam_silently_skips_unsupported_kind(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "test-key")
    session = MagicMock()
    session.get.return_value = _mock_response(_sam_payload("X1", "Acme"))
    adapter = SAMEntitiesAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(
        identifiers=(
            EntityIdentifier(kind="cik", value="0001234"),  # unsupported in SAM
            EntityIdentifier(kind="uei", value="X1"),
        )
    )
    df = adapter.fetch(eq)
    assert len(df) == 1
    # Exactly one HTTP call — only the uei kind was looked up.
    assert session.get.call_count == 1


@pytest.mark.unit
def test_sam_iterates_each_supported_identifier(monkeypatch):
    monkeypatch.setenv("SAM_API_KEY", "test-key")
    session = MagicMock()
    session.get.side_effect = [
        _mock_response(_sam_payload("U1", "Org One")),
        _mock_response(_sam_payload("U2", "Org Two")),
        _mock_response(_sam_payload("U3", "Org Three")),
    ]
    adapter = SAMEntitiesAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(
        identifiers=(
            EntityIdentifier(kind="uei", value="U1"),
            EntityIdentifier(kind="uei", value="U2"),
            EntityIdentifier(kind="name", value="Acme"),
        )
    )
    df = adapter.fetch(eq)
    assert len(df) == 3
    assert session.get.call_count == 3
    assert set(df["uei"]) == {"U1", "U2", "U3"}


@pytest.mark.unit
def test_sam_supported_kinds_matches_param_table():
    assert SAMEntitiesAdapter.supported_kinds == frozenset(PARAM_FOR_KIND.keys())


# ---------------------------------------------------------------------------
# OFAC SDN
# ---------------------------------------------------------------------------


SDN_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<sdnList xmlns="http://tempuri.org/sdnList.xsd">
  <sdnEntry>
    <uid>1001</uid>
    <lastName>EVIL CORP LLC</lastName>
    <sdnType>Entity</sdnType>
    <programList><program>CUBA</program></programList>
    <akaList>
      <aka><lastName>EVIL HOLDINGS</lastName></aka>
    </akaList>
  </sdnEntry>
  <sdnEntry>
    <uid>1002</uid>
    <lastName>SMITH</lastName>
    <firstName>JOHN</firstName>
    <sdnType>Individual</sdnType>
    <programList><program>SDGT</program></programList>
  </sdnEntry>
  <sdnEntry>
    <uid>1003</uid>
    <lastName>LUMA ENERGY OPERATIONS</lastName>
    <sdnType>Entity</sdnType>
    <programList><program>VENEZUELA</program></programList>
  </sdnEntry>
</sdnList>
"""


@pytest.mark.unit
def test_parse_sdn_xml_extracts_entries():
    rows = parse_sdn_xml(SDN_XML)
    assert len(rows) == 3
    names = {r["name"] for r in rows}
    assert "EVIL CORP LLC" in names
    assert "SMITH, JOHN" in names
    assert "LUMA ENERGY OPERATIONS" in names
    # Programs joined with pipe.
    evil = next(r for r in rows if r["uid"] == "1001")
    assert evil["programs"] == "CUBA"
    assert "EVIL HOLDINGS" in evil["aka_names"]


@pytest.mark.unit
def test_ofac_filters_by_name_substring():
    session = MagicMock()
    session.get.return_value = _mock_response(SDN_XML)
    adapter = OFACSDNAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="name", value="LUMA"),))
    df = adapter.fetch(eq)
    assert len(df) == 1
    assert df.iloc[0]["uid"] == "1003"


@pytest.mark.unit
def test_ofac_name_match_searches_aka_field():
    session = MagicMock()
    session.get.return_value = _mock_response(SDN_XML)
    adapter = OFACSDNAdapter(root=REPO_ROOT, session=session)
    # 'EVIL HOLDINGS' is an aka of 'EVIL CORP LLC', not the primary name.
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="name", value="EVIL HOLDINGS"),))
    df = adapter.fetch(eq)
    assert len(df) == 1
    assert df.iloc[0]["uid"] == "1001"


@pytest.mark.unit
def test_ofac_filters_by_uei_against_sdn_uid():
    session = MagicMock()
    session.get.return_value = _mock_response(SDN_XML)
    adapter = OFACSDNAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="1002"),))
    df = adapter.fetch(eq)
    assert len(df) == 1
    assert df.iloc[0]["name"] == "SMITH, JOHN"


@pytest.mark.unit
def test_ofac_returns_empty_df_when_no_match():
    session = MagicMock()
    session.get.return_value = _mock_response(SDN_XML)
    adapter = OFACSDNAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="name", value="DOES NOT EXIST"),))
    df = adapter.fetch(eq)
    assert df.empty


@pytest.mark.unit
def test_ofac_returns_empty_df_when_query_has_no_supported_kinds():
    session = MagicMock()
    session.get.return_value = _mock_response(SDN_XML)
    adapter = OFACSDNAdapter(root=REPO_ROOT, session=session)
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="cik", value="0001234"),))
    df = adapter.fetch(eq)
    assert df.empty


@pytest.mark.unit
def test_ofac_needs_no_credentials():
    # Constructed without env vars; default session uses no auth headers.
    adapter = OFACSDNAdapter(root=REPO_ROOT)
    session = adapter._get_session()
    assert "Authorization" not in session.headers
    assert "X-Api-Key" not in session.headers


@pytest.mark.unit
def test_ofac_supported_kinds_is_name_plus_uei():
    assert OFACSDNAdapter.supported_kinds == frozenset({"name", "uei"})
