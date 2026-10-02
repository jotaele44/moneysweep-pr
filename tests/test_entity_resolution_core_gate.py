from moneysweep.capital_control.resolution_core import CertificationState
from scripts.entity_resolution import adjudicate_usaspending_candidate


def test_usaspending_name_only_candidate_cannot_promote_identity() -> None:
    vendor = {"vendor_name": "Example Corp", "known_uei": ""}
    search = {"name": "Example Corporation", "uei": "UEI_CANDIDATE", "match_score": 0.99}
    result = adjudicate_usaspending_candidate(vendor, search)
    assert result.state is CertificationState.CANDIDATE_NOT_IDENTITY
    assert result.selected_id is None


def test_usaspending_exact_uei_bridge_can_promote_identity() -> None:
    vendor = {"vendor_name": "Example Corp", "known_uei": "UEI_EXACT"}
    search = {"name": "Example Corporation", "uei": "UEI_EXACT", "match_score": 0.80}
    result = adjudicate_usaspending_candidate(vendor, search)
    assert result.state is CertificationState.PASS
    assert result.selected_id == "UEI_EXACT"
