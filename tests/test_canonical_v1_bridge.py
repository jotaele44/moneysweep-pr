"""Tests for the canonical_v1 -> federation bridge (WS-Q)."""
import re

import pytest

from contract_sweeper.federation import canonical_v1_bridge as bridge
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import bridge_canonical_v1_federation as br

REPO_ROOT = cv1.REPO_ROOT

ID_PATTERNS = {
    "sources": ("source_id", r"^src_[a-f0-9]{32}$"),
    "entities": ("entity_id", r"^ent_[a-f0-9]{32}$"),
    "relationships": ("relationship_id", r"^rel_[a-f0-9]{32}$"),
}


@pytest.fixture(scope="module")
def streams():
    return bridge.build_streams(REPO_ROOT)


@pytest.mark.integration
def test_streams_have_expected_shape(streams):
    tables = cv1.load_all_tables(REPO_ROOT)
    # one source per evidence row
    assert len(streams["sources"]) == len(tables["evidence"])
    # entities = canonical entities + people
    assert len(streams["entities"]) == len(tables["entities"]) + len(tables["people"])
    # every edge is either federated or reported
    assert len(streams["relationships"]) + len(streams["not_yet_federated"]) == len(tables["edges"])


@pytest.mark.unit
def test_ids_match_federation_patterns(streams):
    for stream, (id_field, pat) in ID_PATTERNS.items():
        for row in streams[stream]:
            assert re.fullmatch(pat, row[id_field]), (stream, row[id_field])


@pytest.mark.integration
def test_rows_have_required_fields_and_lineage(streams):
    errors = br.validate_rows(streams, REPO_ROOT)
    assert errors == [], errors
    for stream in ("sources", "entities", "relationships"):
        for row in streams[stream]:
            assert row["synthetic"] is False
            assert set(row["lineage"]) >= {"producer_script", "producer_phase", "source_inputs"}


@pytest.mark.integration
def test_relationship_endpoints_resolve_to_emitted_entities(streams):
    entity_ids = {e["entity_id"] for e in streams["entities"]}
    source_ids = {s["source_id"] for s in streams["sources"]}
    for r in streams["relationships"]:
        assert r["source_entity_id"] in entity_ids
        assert r["target_entity_id"] in entity_ids
        assert r["evidence_source_id"] in source_ids
        assert r["relationship_type"] in cv1.EDGE_TYPES


@pytest.mark.unit
def test_bridge_is_idempotent(streams):
    again = bridge.build_streams(REPO_ROOT)
    assert [e["entity_id"] for e in again["entities"]] == [e["entity_id"] for e in streams["entities"]]
    assert [r["relationship_id"] for r in again["relationships"]] == \
           [r["relationship_id"] for r in streams["relationships"]]
