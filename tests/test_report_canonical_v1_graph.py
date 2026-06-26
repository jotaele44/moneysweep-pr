"""Tests for the read-only canonical_v1 graph legibility reporter."""

import json

import pytest

from moneysweep.validation import canonical_v1_schema as cv1
from scripts import report_canonical_v1_graph as rep

REPO_ROOT = cv1.REPO_ROOT


@pytest.fixture(scope="module")
def summary():
    return rep.summarize(REPO_ROOT)


@pytest.mark.integration
def test_summary_counts_match_tables(summary):
    tables = cv1.load_all_tables(REPO_ROOT)
    assert summary["node_counts"]["municipalities"] == len(tables["municipalities"])
    assert summary["node_counts"]["people"] == len(tables["people"])
    assert summary["node_counts"]["entities"] == len(tables["entities"])
    assert summary["edge_count"] == len(tables["edges"])
    assert summary["evidence_count"] == len(tables["evidence"])
    # total_nodes excludes evidence + review_queue (not graph nodes)
    assert summary["total_nodes"] == sum(summary["node_counts"].values())


@pytest.mark.integration
def test_edge_type_counts_sum_to_edge_count(summary):
    assert sum(summary["edge_type_counts"].values()) == summary["edge_count"]


@pytest.mark.integration
def test_edge_coverage_is_a_percentage(summary):
    assert 0.0 <= summary["edge_evidence_coverage_pct"] <= 100.0
    assert summary["edges_backed_by_accepted_evidence"] <= summary["edge_count"]


@pytest.mark.unit
def test_carries_gate_label(summary):
    assert summary["gate"] == "NON_PRODUCTION_DIAGNOSTIC"


@pytest.mark.unit
def test_markdown_renders_and_is_claim_safe(summary):
    md = rep.render_markdown(summary)
    assert "# Canonical v1 Graph Summary" in md
    assert "NON_PRODUCTION_DIAGNOSTIC" in md
    # must avoid forbidden conclusive language (CLAIM_LANGUAGE_POLICY)
    lowered = md.lower()
    for forbidden in ("proves", "confirmed control", "definitive influence"):
        assert forbidden not in lowered


@pytest.mark.integration
def test_write_reports_roundtrips(tmp_path, summary):
    # write into a temp tree mirroring the repo layout
    (tmp_path / "reports").mkdir()
    rep.write_reports(summary, tmp_path)
    written = json.loads((tmp_path / rep.JSON_OUT).read_text())
    assert written["edge_count"] == summary["edge_count"]
    assert (tmp_path / rep.MD_OUT).exists()
