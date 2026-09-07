import pytest

from scripts.build_federation_spatial_bindings_v1_1 import adapt


def test_no_spatial_evidence_remains_unresolved():
    out = adapt({"project_id": "P1"})
    b = out["bindings"][0]
    assert b["canonical_id"] is None
    assert b["cardinality"] == "0:1"
    assert b["identity_state"] == "UNRESOLVED"


def test_municipio_centroid_never_promotes_identity():
    out = adapt(
        {
            "project_id": "P2",
            "spatial_evidence": [
                {
                    "method": "MUNICIPIO_CENTROID",
                    "canonical_id": "fed:place:1",
                    "cardinality": "1:1",
                }
            ],
        }
    )
    b = out["bindings"][0]
    assert b["identity_state"] == "CANDIDATE_NOT_IDENTITY"
    assert "forbidden" in b["reason"]


def test_nearest_only_never_promotes_identity():
    out = adapt(
        {
            "project_id": "P3",
            "spatial_evidence": [
                {"method": "NEAREST_ONLY", "canonical_id": "fed:asset:1", "cardinality": "1:1"}
            ],
        }
    )
    assert out["bindings"][0]["identity_state"] == "CANDIDATE_NOT_IDENTITY"


def test_authoritative_binding_is_only_provisional_until_federation_adjudication():
    out = adapt(
        {
            "project_id": "P4",
            "spatial_evidence": [
                {
                    "method": "AUTHORITATIVE_BINDING",
                    "canonical_id": "fed:parcel:1",
                    "cardinality": "1:1",
                    "source_reference": "CRIM:123",
                }
            ],
        }
    )
    b = out["bindings"][0]
    assert b["identity_state"] == "PROVISIONAL"
    assert b["canonical_id"] == "fed:parcel:1"


def test_one_to_many_cardinality_is_preserved():
    out = adapt(
        {
            "project_id": "P5",
            "spatial_evidence": [
                {
                    "method": "STABLE_ID",
                    "canonical_id": "fed:road:segment-set",
                    "cardinality": "1:N",
                }
            ],
        }
    )
    binding = out["bindings"][0]
    assert binding["cardinality"] == "1:N"
    assert binding["identity_state"] == "UNRESOLVED"


def test_raw_and_normalized_record_ids_remain_separate():
    out = adapt({"project_id": "  P6  "})
    assert out["record_id_raw"] == "  P6  "
    assert out["record_id"] == "P6"
    assert out["bindings"][0]["record_id_raw"] == "  P6  "


@pytest.mark.parametrize("evidence", [{}, "STABLE_ID", ["not-an-object"]])
def test_malformed_evidence_container_fails_closed(evidence):
    with pytest.raises(ValueError, match="spatial_evidence"):
        adapt({"project_id": "P7", "spatial_evidence": evidence})


def test_whitespace_canonical_id_fails_closed():
    with pytest.raises(ValueError, match="canonical_id"):
        adapt(
            {
                "project_id": "P8",
                "spatial_evidence": [
                    {
                        "method": "STABLE_ID",
                        "canonical_id": "   ",
                        "cardinality": "1:1",
                    }
                ],
            }
        )


def test_duplicate_candidates_fail_instead_of_silently_collapsing():
    candidate = {
        "method": "STABLE_ID",
        "canonical_id": "fed:asset:1",
        "cardinality": "1:1",
    }
    with pytest.raises(ValueError, match="duplicate spatial evidence"):
        adapt({"project_id": "P9", "spatial_evidence": [candidate, candidate.copy()]})
