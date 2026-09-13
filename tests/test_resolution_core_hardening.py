import pytest

from moneysweep.capital_control import IdentityCandidate, resolve_identity_candidates
from moneysweep.capital_control.resolution_core import (
    CertificationState,
    ChangeState,
    Contradiction,
    EvidenceBasis,
    FinancialAmount,
    SpatialState,
    adjudicate_contradiction,
    assert_no_unsafe_many_to_many,
    attribute_financial_instrument,
    bind_property_project,
    diff_baseline,
)


def test_legacy_identity_api_delegates_without_behavior_drift() -> None:
    result = resolve_identity_candidates(
        [
            IdentityCandidate("INV_a", "AUTHORITATIVE_BINDING", "filing"),
            IdentityCandidate("INV_b", "STABLE_ID", "stable registry id"),
        ]
    )
    assert result.status == "PASS"
    assert result.selected_id == "INV_b"


def test_property_identity_requires_authoritative_anchor() -> None:
    result = bind_property_project(
        project_ref="PROJECT_Z",
        property_ref="PARCEL_CANDIDATE",
        authoritative_property_anchor=False,
        evidence_basis=EvidenceBasis.PROXIMITY_ONLY,
        spatial_state=SpatialState.UNRESOLVED,
    )
    assert result.state is CertificationState.BLOCKED
    assert result.spatial_state is SpatialState.UNRESOLVED


def test_financial_attribution_requires_project_specific_binding() -> None:
    result = attribute_financial_instrument(
        instrument_ref="CFI::2020-000368",
        amount=FinancialAmount(200000.0, "CONTRACT_AMOUNT", "USD"),
        project_specific_binding=False,
        project_ref=None,
    )
    assert result.state is CertificationState.BLOCKED


def test_unsafe_many_to_many_join_fails_closed() -> None:
    with pytest.raises(ValueError, match="many-to-many"):
        assert_no_unsafe_many_to_many(["A", "A"], ["A", "A"])


def test_contradiction_adjudication_preserves_superseded_observation() -> None:
    contradiction = Contradiction(
        "RS564_VOTE",
        "COUNT",
        ("17-7-4", "23-4-1"),
    )
    result = adjudicate_contradiction(
        contradiction,
        controlling_observation="17-7-4",
        superseded_observations=("23-4-1",),
        reason="23-4-1 belongs to adjacent measure",
    )
    assert result.state is CertificationState.PASS
    assert result.controlling_observation == "17-7-4"
    assert result.superseded_observations == ("23-4-1",)


def test_change_detection_reopens_only_changed_keys() -> None:
    result = diff_baseline(
        {"ARPE": "PRIMARY_INTERFACE_REQUIRED", "DOS": "PRIMARY_INTERFACE_REQUIRED"},
        {"ARPE": "PASS", "DOS": "PRIMARY_INTERFACE_REQUIRED"},
    )
    assert result.state is ChangeState.CHANGED
    assert result.changed_keys == ("ARPE",)
