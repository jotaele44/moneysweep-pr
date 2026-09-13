from moneysweep.capital_control.resolution_core import (
    Cardinality,
    CertificationState,
    EvidenceBasis,
    PropositionType,
    make_proposition,
)


def test_all_required_cardinalities_exist() -> None:
    assert {item.value for item in Cardinality} == {
        "1:1",
        "1:N",
        "N:1",
        "N:N",
        "0:1",
        "UNRESOLVED",
    }


def test_identifier_and_event_identity_can_diverge() -> None:
    identifier = make_proposition(
        "p-id",
        PropositionType.IDENTIFIER_IDENTITY,
        "DDEC::358",
        "equals",
        "CFI::Aggregate-ID",
        cardinality=Cardinality.ONE_TO_ONE,
        state=CertificationState.FAIL,
        evidence_basis=EvidenceBasis.STABLE_ID,
    )
    event = make_proposition(
        "p-event",
        PropositionType.EVENT_IDENTITY,
        "DDEC::FIE0057",
        "same-event",
        "CFI::368",
        cardinality=Cardinality.ONE_TO_ONE,
        state=CertificationState.PROVISIONAL,
        evidence_basis=EvidenceBasis.AUTHORITATIVE_BINDING,
    )
    assert identifier.state is CertificationState.FAIL
    assert event.state is CertificationState.PROVISIONAL
