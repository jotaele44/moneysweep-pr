"""Regression gates for the frozen MII v0.3 provisional ingestion path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from moneysweep.entity_network.mii_v03 import (
    MIIReferenceError,
    PDF_SHA256,
    REFERENCE_DIR,
    ZIP_SHA256,
    mii_evidence_is_binding,
    validate_reference_bundle,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / REFERENCE_DIR


def _load(name: str) -> dict:
    return json.loads((REF / name).read_text(encoding="utf-8"))


def test_reference_bundle_closes_bounded_arithmetic() -> None:
    result = validate_reference_bundle(REF)
    assert result == {
        "status": "PASS",
        "sector_count": 10,
        "source_vector_count": 10,
        "source_contradiction_count": 6,
        "ingest_contradiction_count": 2,
        "row_level_edge_state": "BLOCKED_SOURCE_ARTIFACT_NOT_EXPOSED",
    }


def test_frozen_source_manifest_binds_exact_outer_and_member_payloads() -> None:
    manifest = _load("source_manifest.json")
    artifacts = {item["name"]: item for item in manifest["artifacts"]}
    pdf = artifacts["PR ecosystem network · MII v0.3.pdf"]
    archive = artifacts["PR ecosystem network · MII v0.3.zip"]

    assert pdf["sha256"] == PDF_SHA256
    assert pdf["size_bytes"] == 14_104_181
    assert pdf["page_count"] == 10
    assert archive["sha256"] == ZIP_SHA256
    assert archive["size_bytes"] == 246_992
    assert archive["member_count"] == 6
    assert archive["uncompressed_size_total"] == 246_344

    member_paths = [row["path"] for row in archive["members"]]
    assert member_paths == [
        "Main.dc.html",
        "ds/pr-int/styles.css",
        "support.js",
        "vendor/react.js",
        "vendor/react-dom.js",
        "README.md",
    ]
    assert len({row["sha256"] for row in archive["members"]}) == 6


def test_mii_evidence_classes_never_become_identity_binding() -> None:
    assert all(mii_evidence_is_binding(value) is False for value in ("A", "B", "C"))
    with pytest.raises(MIIReferenceError, match="unknown MII evidence class"):
        mii_evidence_is_binding("T1")


def test_declared_sector_denominator_and_node_residue_close_without_synthesis() -> None:
    coverage = _load("coverage_ledger.json")["sectors"]
    assert len(coverage) == 10
    assert sum(row["declared_curated_nodes"] for row in coverage) == 223
    assert sum(row["visible_unique_card_signatures"] for row in coverage) == 182
    assert sum(row["row_level_curated_node_residue"] for row in coverage) == 41
    assert 182 + 41 == 223

    residues = {
        row["mii_label"]: row["row_level_curated_node_residue"]
        for row in coverage
        if row["row_level_curated_node_residue"]
    }
    assert residues == {
        "PHARMA": 26,
        "AERODEF": 11,
        "WATER": 1,
        "INDUSTRIAL": 3,
    }


def test_water_count_contradiction_is_not_silently_repaired() -> None:
    coverage = {
        row["mii_label"]: row
        for row in _load("coverage_ledger.json")["sectors"]
    }
    water = coverage["WATER"]
    assert water["declared_curated_nodes"] == 4
    assert water["node_evidence_tally_sum"] == 3
    assert water["node_evidence_tally_closes"] is False

    contradictions = _load("contradictions.json")["ingest_contradictions"]
    by_id = {row["contradiction_id"]: row for row in contradictions}
    assert by_id["MII-INGEST-COUNT-001"]["state"] == "UNRESOLVED"


def test_health_registry_count_conflict_remains_unresolved() -> None:
    contradictions = _load("contradictions.json")["ingest_contradictions"]
    by_id = {row["contradiction_id"]: row for row in contradictions}
    row = by_id["MII-INGEST-COUNT-002"]
    assert row["observation_a"] == "coverage ledger core_candidates=208"
    assert row["observation_b"] == "final note says registry only: 2,175 candidates"
    assert row["state"] == "UNRESOLVED"


def test_edge_arithmetic_closes_but_row_level_edges_remain_blocked() -> None:
    reconciliation = _load("reconciliation.json")
    edge = reconciliation["edge_arithmetic"]
    assert edge["global_distinct_edges"] == 213
    assert edge["cross_ecosystem_edges"] == 59
    assert edge["internal_edges_computed"] == 154
    assert edge["sum_ecosystem_board_edges"] == 272
    assert 154 + 2 * 59 == 272
    assert edge["row_level_edge_ingest_state"] == (
        "BLOCKED_SOURCE_ARTIFACT_NOT_EXPOSED"
    )
    assert reconciliation["materialized_from_visible_pdf"][
        "row_level_edges_materialized"
    ] == 0


def test_source_contradiction_denominator_is_exactly_six() -> None:
    contradictions = _load("contradictions.json")["source_contradictions"]
    assert [row["contradiction_id"] for row in contradictions] == [
        "V3C-001",
        "V3C-002",
        "V3C-003",
        "V3C-004",
        "V3C-005",
        "V3C-006",
    ]
    assert all(row["state"] == "OPEN" for row in contradictions)


def test_source_vector_binding_is_not_source_exhaustion() -> None:
    bindings = _load("source_bindings.json")
    by_vector = {row["vector_id"]: row for row in bindings["bindings"]}

    assert len(by_vector) == 10
    assert by_vector["MII-SRC-02"]["binding_state"] == "MISSING_ADAPTER"
    assert by_vector["MII-SRC-06"]["binding_state"] == (
        "PARTIAL_MISSING_PREB_ADAPTER"
    )
    assert by_vector["MII-SRC-07"]["binding_state"] == "CANDIDATE_NOT_EQUIVALENT"
    assert by_vector["MII-SRC-08"]["binding_state"] == (
        "PARTIAL_MISSING_PRIDCO_LEASE_ADAPTER"
    )
    assert "Registration or materialization does not prove" in bindings["semantics"]


def test_observed_row_extraction_hashes_are_frozen() -> None:
    observed = _load("reconciliation.json")["materialized_from_visible_pdf"]
    assert observed["rendered_card_manifestations"] == 256
    assert observed["distinct_visible_card_signatures"] == 182
    assert observed["visible_registry_name_only_candidates"] == 28
    assert observed["observed_visible_node_cards_sha256"] == (
        "f54de82e8d04eb0e6c2bac4a549b45463706b545ece9ff0b1021d84894be440c"
    )
    assert observed["observed_visible_registry_candidates_sha256"] == (
        "8d3ef4957db0c654372596506a7f0bce1b00c388ef82c380d19c84a55818dbcc"
    )


def test_identity_boundaries_are_all_fail_closed() -> None:
    boundaries = _load("source_manifest.json")["identity_boundaries"]
    assert boundaries == {
        "source_manifestation_is_canonical_identity": False,
        "mii_evidence_class_is_resolution_core_binding": False,
        "registry_name_candidate_is_identity": False,
        "missing_row_may_be_synthesized": False,
    }
