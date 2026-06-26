"""Tests for deterministic canonical_v1 ID generation + person-name normalization."""

import re

import pytest

from moneysweep.runtime import canonical_ids as cid
from moneysweep.runtime.name_normalization import normalize_person_name

ID_PATTERNS = {
    "person": r"^person_[A-Za-z0-9_]+$",
    "entity": r"^entity_[A-Za-z0-9_]+$",
    "contract": r"^contract_[A-Za-z0-9_]+$",
    "project": r"^project_[A-Za-z0-9_]+$",
    "debt": r"^debt_[A-Za-z0-9_]+$",
    "lobby": r"^lobby_[A-Za-z0-9_]+$",
    "funding": r"^funding_[A-Za-z0-9_]+$",
    "muni": r"^muni_pr_[A-Za-z0-9_]+$",
    "edge": r"^edge_[A-Za-z0-9_]+$",
    "evidence": r"^evidence_[A-Za-z0-9_]+$",
}


@pytest.mark.unit
def test_all_generators_match_schema_patterns():
    assert re.fullmatch(ID_PATTERNS["person"], cid.person_id("Pedro Pierluisi"))
    assert re.fullmatch(ID_PATTERNS["entity"], cid.entity_id("Autopistas Metropolitanas, LLC"))
    assert re.fullmatch(ID_PATTERNS["contract"], cid.contract_id("ACT", "2019-000123"))
    assert re.fullmatch(ID_PATTERNS["project"], cid.project_id("PRASA", "CIP-7"))
    assert re.fullmatch(ID_PATTERNS["debt"], cid.debt_id("COFINA", "COFINA", 2018))
    assert re.fullmatch(ID_PATTERNS["lobby"], cid.lobbying_id("PR", "REG-42", "2024Q1"))
    assert re.fullmatch(ID_PATTERNS["funding"], cid.funding_id("CDBG-DR", 2020))
    assert re.fullmatch(ID_PATTERNS["muni"], cid.municipality_id("San Juan"))
    assert re.fullmatch(r"^property_[A-Za-z0-9_]+$", cid.property_id("PR-22 Toll Road", "HTA"))
    assert re.fullmatch(
        ID_PATTERNS["edge"], cid.edge_id("entity_a", "OWNS_OR_CONTROLS", "entity_b")
    )
    assert re.fullmatch(ID_PATTERNS["evidence"], cid.evidence_id("EMMA filing", "p.12", "claim"))


@pytest.mark.unit
def test_ids_are_idempotent():
    assert cid.person_id("Jane Doe") == cid.person_id("Jane Doe")
    assert cid.entity_id("PREPA") == cid.entity_id("PREPA")
    assert cid.edge_id("a", "REPRESENTS", "b") == cid.edge_id("a", "REPRESENTS", "b")
    assert cid.evidence_id("s", "r", "c") == cid.evidence_id("s", "r", "c")


@pytest.mark.unit
def test_person_id_clusters_aliases_and_accents():
    # generational suffix + accents + case must not change identity
    assert cid.person_id("Pedro Pierluisi") == cid.person_id("PEDRO PIERLUISI JR.")
    assert cid.person_id("José Rodríguez") == cid.person_id("Jose Rodriguez")


@pytest.mark.unit
def test_distinct_inputs_yield_distinct_ids():
    assert cid.person_id("Jane Doe") != cid.person_id("John Doe")
    assert cid.entity_id("PREPA") != cid.entity_id("PRASA")


@pytest.mark.unit
def test_edge_id_is_direction_and_type_sensitive():
    assert cid.edge_id("a", "OWNS_OR_CONTROLS", "b") != cid.edge_id("b", "OWNS_OR_CONTROLS", "a")
    assert cid.edge_id("a", "OWNS_OR_CONTROLS", "b") != cid.edge_id("a", "ADVISES", "b")


@pytest.mark.unit
def test_contract_id_is_human_legible():
    assert cid.contract_id("ACT", "2019/000-123") == "contract_act_2019_000_123"


@pytest.mark.unit
def test_slug_handles_empty():
    assert cid.slug("") == "na"
    assert cid.slug(None) == "na"
    assert cid.slug("  Foo Bar!! ") == "foo_bar"


@pytest.mark.unit
def test_normalize_person_name_keeps_two_surnames():
    assert normalize_person_name("Wanda Vázquez Garced") == "WANDA VAZQUEZ GARCED"
    assert normalize_person_name("") == ""
