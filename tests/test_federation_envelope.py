"""Envelope + namespacing contract tests for the Contract-Sweeper producer."""
from __future__ import annotations

import pytest

from contract_sweeper.federation.envelope import EvidenceEnvelope, entity_ref
from contract_sweeper.federation.namespace import (
    PREFIX,
    is_namespaced,
    namespaced_id,
)


def test_namespaced_id_prefixes_raw():
    assert namespaced_id("award_abc") == "contract_sweeper:award_abc"


def test_namespaced_id_is_idempotent():
    once = namespaced_id("ent_acme")
    assert namespaced_id(once) == once
    assert is_namespaced(once)


def test_namespaced_id_rejects_empty():
    with pytest.raises(ValueError):
        namespaced_id("")
    with pytest.raises(ValueError):
        namespaced_id(None)


def test_is_namespaced_false_for_bare_prefix():
    assert not is_namespaced("contract_sweeper:")
    assert not is_namespaced("award_abc")


def test_envelope_round_trips_through_dict():
    env = EvidenceEnvelope(
        producer=PREFIX,
        record_type="entity",
        record_id=namespaced_id("ent_acme"),
        source_id=namespaced_id("src_usaspending"),
        entities=[entity_ref(namespaced_id("ent_acme"), "ACME", "ACME")],
    )
    d = env.to_dict()
    assert set(d) == {
        "producer", "record_type", "record_id", "source_id", "timestamp",
        "geo", "entities", "confidence", "lineage", "payload", "synthetic",
    }
    assert EvidenceEnvelope.from_dict(d).to_dict() == d


def test_from_dict_requires_core_keys():
    with pytest.raises(ValueError):
        EvidenceEnvelope.from_dict({"producer": "x"})
