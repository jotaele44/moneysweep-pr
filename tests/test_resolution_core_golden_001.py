from moneysweep.capital_control.resolution_core import (
    Candidate,
    CertificationState,
    EvidenceBasis,
    NamespaceBinding,
    NamespaceRegistry,
    close_grant,
    compute_equivalence_sets,
    evaluate_foia_gate,
    federation_unlock,
    funding_unlock,
    parcel_unlock,
    resolve_candidates,
)


def test_namespace_occupancy_preserves_ddec_cfi_separation() -> None:
    registry = NamespaceRegistry()
    assert (
        registry.register(NamespaceBinding("CFI", "2020-000368", "Aggregate", "CFI-row-368")).state
        is CertificationState.PASS
    )
    assert (
        registry.register(NamespaceBinding("CFI", "2020-000358", "Starbright", "CFI-row-358")).state
        is CertificationState.PASS
    )

    conflict = registry.register(
        NamespaceBinding("CFI", "2020-000358", "Aggregate", "DDEC-FIE0057")
    )
    assert conflict.state is CertificationState.FAIL
    assert conflict.conflict is not None
    assert conflict.conflict.subject_ref == "Starbright"

    # DDEC's persistent RAW field is valid in its own source namespace.
    assert (
        registry.register(NamespaceBinding("DDEC", "2020-000358", "FIE0057", "DDEC-FIE0057")).state
        is CertificationState.PASS
    )


def test_tied_top_binding_evidence_fails_closed() -> None:
    result = resolve_candidates(
        [
            Candidate("A", EvidenceBasis.STABLE_ID, "source:a"),
            Candidate("B", EvidenceBasis.STABLE_ID, "source:b"),
        ]
    )
    assert result.state is CertificationState.UNRESOLVED
    assert result.selected_id is None
    assert len(result.candidates) == 2


def test_proximity_only_is_candidate_not_identity() -> None:
    result = resolve_candidates([Candidate("parcel-a", EvidenceBasis.PROXIMITY_ONLY, "nearest")])
    assert result.state is CertificationState.CANDIDATE_NOT_IDENTITY
    assert result.selected_id is None


def test_fie0057_cfi368_equivalence_sets_are_complete() -> None:
    result = compute_equivalence_sets(
        {"name", "amount", "date", "358"},
        {"name", "amount", "date", "368"},
    )
    assert result.intersection == frozenset({"name", "amount", "date"})
    assert result.a_only == frozenset({"358"})
    assert result.b_only == frozenset({"368"})
    assert result.union == frozenset({"name", "amount", "date", "358", "368"})
    assert result.symmetric_difference == frozenset({"358", "368"})


def test_ddec_grant_closeout_arithmetic() -> None:
    result = close_grant(
        authorized=200000,
        disbursed=183459.50,
        cancelled=16540.50,
        balance=0,
    )
    assert result.state is CertificationState.PASS
    assert abs(result.delta) < 1e-9


def test_unlock_graph_requires_exact_prerequisites() -> None:
    assert (
        parcel_unlock({"authoritative_property_anchor": CertificationState.OPEN}).state
        is CertificationState.BLOCKED
    )
    assert (
        federation_unlock({"stable_id_bridge": CertificationState.PASS}).state
        is CertificationState.PASS
    )
    assert (
        funding_unlock({"project_specific_binding": CertificationState.PROVISIONAL}).state
        is CertificationState.BLOCKED
    )


def test_foia_blocks_on_reachable_residue() -> None:
    result = evaluate_foia_gate(
        {
            "ARPE": CertificationState.PRIMARY_INTERFACE_REQUIRED,
            "SUMAC88": CertificationState.PRIMARY_INTERFACE_REQUIRED,
            "DOS": CertificationState.PRIMARY_INTERFACE_REQUIRED,
            "FIE0057_CFI368": CertificationState.PRIMARY_ARTIFACT_NOT_FOUND,
            "GIS_GEODATA": CertificationState.DEMONSTRABLY_INACCESSIBLE,
        }
    )
    assert result.state is CertificationState.BLOCKED
    assert result.blockers == ("ARPE", "DOS", "FIE0057_CFI368", "SUMAC88")


def test_foia_passes_only_terminal_public_states() -> None:
    result = evaluate_foia_gate(
        {
            "ARPE": CertificationState.PASS,
            "SUMAC88": CertificationState.NEGATIVELY_CLOSED,
            "DOS": CertificationState.PASS,
            "GIS_GEODATA": CertificationState.DEMONSTRABLY_INACCESSIBLE,
        }
    )
    assert result.state is CertificationState.PASS
