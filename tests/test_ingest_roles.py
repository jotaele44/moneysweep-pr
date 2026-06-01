"""Tests for the canonical_v1 roles ingester (WS-L), using synthetic data only."""
import csv
from pathlib import Path

import pytest

from contract_sweeper.runtime.canonical_ids import entity_id, person_id
from contract_sweeper.validation import canonical_v1_schema as cv1
from scripts import ingest_roles as ir

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "canonical_v1_roles_sample.csv"


def _seed_root(tmp_path: Path) -> Path:
    """Build a minimal canonical_v1 tree with synthetic person + entity nodes."""
    d = tmp_path / "data" / "canonical_v1"
    d.mkdir(parents=True)
    with (d / "people.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["person_id", "full_name", "normalized_name", "aliases",
                    "primary_role", "primary_entity_id", "jurisdiction",
                    "confidence", "evidence_id", "review_status", "notes"])
        w.writerow([person_id("Alice Verified"), "Alice Verified", "ALICE VERIFIED",
                    "", "", "", "", "0.9", "", "accepted", ""])
    with (d / "entities.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["entity_id", "name", "normalized_name", "entity_type",
                    "parent_entity_id", "jurisdiction", "registry_ids",
                    "confidence", "evidence_id", "review_status", "notes"])
        w.writerow([entity_id("Test Utility Authority"), "Test Utility Authority",
                    "TEST UTILITY AUTHORITY", "utility", "", "PR", "",
                    "0.9", "", "accepted", ""])
    # municipalities.csv is read by the shared resolver; an empty table is fine
    with (d / "municipalities.csv").open("w", newline="", encoding="utf-8") as fh:
        csv.writer(fh).writerow(["municipality_id", "name", "normalized_name",
                                 "region", "county_fips", "aliases", "confidence",
                                 "evidence_id", "review_status", "notes"])
    return tmp_path


@pytest.fixture
def built(tmp_path, monkeypatch):
    root = _seed_root(tmp_path)
    monkeypatch.setattr(ir, "ROLES_SOURCE", str(FIXTURE))
    return ir.build_records(root)


@pytest.mark.integration
def test_only_resolvable_valid_roles_are_kept(built):
    assert len(built["role_rows"]) == 1
    reasons = " ".join(s["reason"] for s in built["skipped"])
    assert "unresolved person" in reasons
    assert "unresolved entity" in reasons
    assert "invalid role_category" in reasons


@pytest.mark.integration
def test_role_rows_and_evidence_validate(built):
    role_schema = cv1.load_schema("roles", cv1.REPO_ROOT)
    ev_schema = cv1.load_schema("evidence", cv1.REPO_ROOT)
    evidence_ids = {e.evidence_id for e in built["evidence_rows"]}
    for row in built["role_rows"]:
        assert cv1.validate_row(row, role_schema) == [], row
        assert row["evidence_id"] in evidence_ids        # no provenance -> no row
        assert row["role_category"] in ir.VALID_CATEGORIES
    for ev in built["evidence_rows"]:
        assert cv1.validate_row(ev.as_row(), ev_schema) == [], ev


@pytest.mark.unit
def test_role_id_is_deterministic(built):
    row = built["role_rows"][0]
    assert row["role_id"] == ir.role_id(row["person_id"], row["entity_id"], row["role_title"])


@pytest.mark.integration
def test_repo_fomb_roles_resolve_against_real_nodes():
    """The committed FOMB seed must fully resolve against the real nodes on disk."""
    built = ir.build_records(cv1.REPO_ROOT)
    assert built["skipped"] == []
    assert len(built["role_rows"]) == 7
    assert {r["role_category"] for r in built["role_rows"]} == {"board"}
