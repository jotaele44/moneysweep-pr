"""Tests for the federal-publications source feed composed into the
canonical_v1 -> federation bridge export (Z6)."""

import json

import pytest

from moneysweep.federation import canonical_v1_bridge as bridge
from scripts import bridge_canonical_v1_federation as br

REPO_ROOT = bridge.REPO_ROOT


def _base():
    return {"sources": [], "entities": [], "relationships": [], "not_yet_federated": []}


def _pub(sid, **over):
    row = {
        "source_id": sid,
        "source_type": "Technical Report",
        "source_name": "Example publication",
        "source_url": "https://example.test/" + sid,
        "confidence": 1.0,
        "lineage": {
            "producer_script": "scripts/ingest_federal_publications.py",
            "producer_phase": br.FEDERAL_PUBLICATIONS_PHASE,
            "source_inputs": ["Puerto_Rico_Federal_Publications_Master_v7.xlsx"],
        },
        "synthetic": False,
        "created_at": "2024-01-01T00:00:00Z",
        "extracted_at": "2024-01-01T00:00:00Z",
    }
    row.update(over)
    return row


def _write_feed(tmp_path, rows):
    d = tmp_path / "data" / "sources"
    d.mkdir(parents=True)
    (d / "federal_publications.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return tmp_path


@pytest.mark.unit
def test_merge_appends_publications(tmp_path):
    root = _write_feed(tmp_path, [_pub("src_" + "a" * 32), _pub("src_" + "b" * 32)])
    streams = _base()
    added = br.merge_external_sources(streams, root)
    assert added == 2
    assert len(streams["sources"]) == 2
    assert all(
        s["lineage"]["producer_phase"] == br.FEDERAL_PUBLICATIONS_PHASE for s in streams["sources"]
    )


@pytest.mark.unit
def test_merge_dedups_by_source_id(tmp_path):
    sid = "src_" + "a" * 32
    root = _write_feed(tmp_path, [_pub(sid), _pub(sid)])  # internal dup + already present
    streams = {"sources": [_pub(sid)], "entities": [], "relationships": [], "not_yet_federated": []}
    added = br.merge_external_sources(streams, root)
    assert added == 0
    assert len(streams["sources"]) == 1


@pytest.mark.unit
def test_merge_is_deterministic_sorted_order(tmp_path):
    root = _write_feed(
        tmp_path, [_pub("src_" + "c" * 32), _pub("src_" + "a" * 32), _pub("src_" + "b" * 32)]
    )
    streams = _base()
    br.merge_external_sources(streams, root)
    ids = [s["source_id"] for s in streams["sources"]]
    assert ids == sorted(ids)


@pytest.mark.unit
def test_merge_only_touches_sources(tmp_path):
    root = _write_feed(tmp_path, [_pub("src_" + "a" * 32)])
    streams = {
        "sources": [],
        "entities": [{"entity_id": "ent_x"}],
        "relationships": [{"relationship_id": "rel_x"}],
        "not_yet_federated": [],
    }
    br.merge_external_sources(streams, root)
    assert streams["entities"] == [{"entity_id": "ent_x"}]
    assert streams["relationships"] == [{"relationship_id": "rel_x"}]


@pytest.mark.unit
def test_missing_feed_returns_zero(tmp_path):
    streams = _base()
    assert br.merge_external_sources(streams, tmp_path) == 0


@pytest.mark.integration
def test_merged_publications_pass_validate_rows(tmp_path):
    root = _write_feed(tmp_path, [_pub("src_" + "a" * 32)])
    streams = _base()
    br.merge_external_sources(streams, root)
    # validate the sources stream against the real schema
    errors = [e for e in br.validate_rows(streams, REPO_ROOT) if e.startswith("[sources")]
    assert errors == [], errors


@pytest.mark.integration
def test_real_feed_keeps_entities_and_edges_unchanged():
    """On the real repo: composing the feed adds sources only; entities,
    relationships, and edges_federated_pct (100%) are untouched."""
    streams = bridge.build_streams(REPO_ROOT)
    n_sources = len(streams["sources"])
    n_entities = len(streams["entities"])
    n_relationships = len(streams["relationships"])
    assert streams["not_yet_federated"] == []  # 100% federated before

    added = br.merge_external_sources(streams, REPO_ROOT)
    assert added > 0
    assert len(streams["sources"]) == n_sources + added
    assert len(streams["entities"]) == n_entities
    assert len(streams["relationships"]) == n_relationships
    assert streams["not_yet_federated"] == []  # still 100% federated
