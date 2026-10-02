"""Regression gates for the additive cross-sector entity-network kernel."""

from pathlib import Path

import pytest
import yaml

from moneysweep.capital_control.resolution_core import (
    Candidate,
    CertificationState,
    EvidenceBasis,
)
from moneysweep.entity_network import (
    MoneyFlowObservation,
    RelationshipAssertion,
    RelationshipFamily,
    Sector,
    SectorMembership,
    guard_join_cardinality,
    index_sector_memberships,
    promotable_relationship,
    resolve_entity_candidates,
    validate_membership_batch,
)

pytestmark = pytest.mark.unit

ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(name: str) -> dict:
    path = ROOT / "config" / "entity_network" / name
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_sector_profile_denominator_is_exact_and_unique() -> None:
    payload = _load_yaml("sector_profiles.yml")
    profile_ids = [row["id"] for row in payload["sectors"]]
    assert len(profile_ids) == 15
    assert len(profile_ids) == len(set(profile_ids))
    assert set(profile_ids) == {sector.value for sector in Sector}


def test_relationship_contract_keeps_money_flows_out_of_graph_edges() -> None:
    payload = _load_yaml("relationship_contract.yml")
    relation_ids = {row["id"] for row in payload["relationship_types"]}
    money_verbs = {"PAYS", "RECEIVES", "INVESTS_IN", "LENDS_TO"}
    assert money_verbs.isdisjoint(relation_ids)
    assert payload["rules"]["money_flow_is_separate"] is True
    assert payload["rules"]["unknown_amount_defaults_to_zero"] is False


def test_relationship_families_in_config_are_known() -> None:
    payload = _load_yaml("relationship_contract.yml")
    allowed = {family.value for family in RelationshipFamily}
    assert {row["family"] for row in payload["relationship_types"]} <= allowed


def test_multi_sector_membership_is_preserved_not_collapsed() -> None:
    rows = [
        SectorMembership(
            "ent_1",
            Sector.ENERGY_FUELS_GRID,
            "contractor",
            "src_a",
        ),
        SectorMembership(
            "ent_1",
            Sector.INDUSTRIAL_MANUFACTURING_EPC_CONSTRUCTION,
            "manufacturer",
            "src_b",
        ),
    ]
    index = index_sector_memberships(rows)
    assert index["ent_1"] == {
        Sector.ENERGY_FUELS_GRID,
        Sector.INDUSTRIAL_MANUFACTURING_EPC_CONSTRUCTION,
    }


def test_duplicate_membership_observation_fails_closed() -> None:
    row = SectorMembership(
        "ent_1",
        Sector.ENERGY_FUELS_GRID,
        "utility",
        "src_a",
    )
    with pytest.raises(ValueError, match="duplicate sector-membership"):
        validate_membership_batch([row, row])


def test_name_or_heuristic_candidate_never_becomes_identity() -> None:
    result = resolve_entity_candidates(
        [
            Candidate(
                "entity_a",
                EvidenceBasis.HEURISTIC_DISCOVERY_ONLY,
                "normalized-name-only",
            )
        ]
    )
    assert result.state is CertificationState.CANDIDATE_NOT_IDENTITY
    assert result.selected_id is None


def test_tied_top_evidence_remains_unresolved() -> None:
    result = resolve_entity_candidates(
        [
            Candidate("entity_a", EvidenceBasis.STABLE_ID, "src_a"),
            Candidate("entity_b", EvidenceBasis.STABLE_ID, "src_b"),
        ]
    )
    assert result.state is CertificationState.UNRESOLVED
    assert result.selected_id is None
    assert len(result.candidates) == 2


def test_relationship_promotion_requires_pass_and_binding_evidence() -> None:
    heuristic = RelationshipAssertion(
        "rel_1",
        "ent_a",
        "DEPENDENCY_ON",
        "ent_b",
        RelationshipFamily.INFRASTRUCTURE,
        "src_a",
        evidence_basis=EvidenceBasis.HEURISTIC_DISCOVERY_ONLY,
        state=CertificationState.PASS,
    )
    binding = RelationshipAssertion(
        "rel_2",
        "ent_a",
        "OWNS",
        "asset_b",
        RelationshipFamily.OWNERSHIP_CONTROL,
        "src_b",
        evidence_basis=EvidenceBasis.AUTHORITATIVE_BINDING,
        state=CertificationState.PASS,
    )
    assert promotable_relationship(heuristic) is False
    assert promotable_relationship(binding) is True


def test_money_flow_unknown_is_null_not_zero() -> None:
    row = MoneyFlowObservation(
        "flow_1",
        "ent_a",
        "ent_b",
        "PAYMENT",
        "src_a",
    )
    assert row.amount is None
    assert row.currency is None


def test_money_flow_rejects_negative_amount_and_bad_currency() -> None:
    with pytest.raises(ValueError, match="amount cannot be negative"):
        MoneyFlowObservation(
            "flow_1",
            "ent_a",
            "ent_b",
            "PAYMENT",
            "src_a",
            amount=-1.0,
            currency="USD",
        )
    with pytest.raises(ValueError, match="three-letter uppercase currency"):
        MoneyFlowObservation(
            "flow_2",
            "ent_a",
            "ent_b",
            "PAYMENT",
            "src_a",
            amount=1.0,
            currency="usd",
        )


def test_relationship_rejects_self_edges_and_inverted_intervals() -> None:
    with pytest.raises(ValueError, match="self relationships"):
        RelationshipAssertion(
            "rel_1",
            "ent_a",
            "OWNS",
            "ent_a",
            RelationshipFamily.OWNERSHIP_CONTROL,
            "src_a",
        )
    with pytest.raises(ValueError, match="valid_to cannot precede valid_from"):
        SectorMembership(
            "ent_a",
            Sector.PHARMA_BIOTECH_MEDDEV,
            "manufacturer",
            "src_a",
            valid_from="2026-10-02",
            valid_to="2026-10-01",
        )


def test_unsafe_many_to_many_join_fails_closed() -> None:
    with pytest.raises(ValueError, match="unsafe many-to-many"):
        guard_join_cardinality(["x", "x"], ["x", "x"])
