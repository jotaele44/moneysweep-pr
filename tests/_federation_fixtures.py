"""Synthetic federation export streams for Contract-Sweeper tests.

Not a test module (no ``test_`` prefix, so pytest does not collect it). Builds a
small, deterministic, synthetic funding/entity package used by the producer
tests and to materialize the committed fixture under
``tests/fixtures/federation/contract_sweeper_export``.
"""
from __future__ import annotations

from typing import Dict, List

from contract_sweeper.federation.envelope import EvidenceEnvelope, entity_ref
from contract_sweeper.federation.export_writer import build_award, build_entity
from contract_sweeper.federation.namespace import PRODUCER, namespaced_id
from contract_sweeper.runtime.linkage_confidence import LinkSignals
from contract_sweeper.runtime.name_normalization import normalize_name

SOURCE_ID = "src_usaspending"


def build_streams(*, synthetic: bool = True) -> Dict[str, List[EvidenceEnvelope]]:
    """Return the synthetic CS package as stream-name -> list[envelope]."""
    acme = build_entity("ent_acme", "ACME CONSTRUCTION INC", source_id=SOURCE_ID, synthetic=synthetic)
    navy = build_entity("ent_navy", "Department of the Navy", source_id=SOURCE_ID, synthetic=synthetic)

    acme_ref = acme.entities[0]
    navy_ref = navy.entities[0]

    award = build_award(
        "award_abc123",
        source_id=SOURCE_ID,
        amount=1234567.89,
        currency="USD",
        award_date="2023-03-15T00:00:00Z",
        entities=[acme_ref, navy_ref],
        signals=LinkSignals(has_prime_award_id=True, has_prime_name=True, has_prime_uei=True),
        synthetic=synthetic,
        payload={"agency": "Department of the Navy", "piid": "W911NF20C0001"},
    )

    transaction = EvidenceEnvelope(
        producer=PRODUCER,
        record_type="transaction",
        record_id=namespaced_id("txn_001"),
        source_id=namespaced_id(SOURCE_ID),
        timestamp="2023-03-18T00:00:00Z",
        entities=[acme_ref],
        confidence={"score": 0.88, "method": "producer_contract"},
        lineage=[{"stage": "transaction_ingest"}],
        payload={"amount": 500000.0, "currency": "USD", "award_id": namespaced_id("award_abc123")},
        synthetic=synthetic,
    )

    relationship = EvidenceEnvelope(
        producer=PRODUCER,
        record_type="relationship",
        record_id=namespaced_id("rel_001"),
        source_id=namespaced_id(SOURCE_ID),
        timestamp="2023-03-15T00:00:00Z",
        entities=[acme_ref, navy_ref],
        confidence={"score": 0.9, "method": "producer_contract"},
        lineage=[{"stage": "relationship_resolution"}],
        payload={"relationship_type": "awarded_by"},
        synthetic=synthetic,
    )

    source = EvidenceEnvelope(
        producer=PRODUCER,
        record_type="source",
        record_id=namespaced_id(SOURCE_ID),
        source_id=namespaced_id(SOURCE_ID),
        timestamp="2023-03-01T00:00:00Z",
        confidence={"score": 1.0, "method": "producer_contract"},
        lineage=[{"stage": "source_registry"}],
        payload={"name": "USAspending.gov", "cadence": "daily"},
        synthetic=synthetic,
    )

    return {
        "funding_awards": [award],
        "transactions": [transaction],
        "entities": [acme, navy],
        "relationships": [relationship],
        "sources": [source],
    }


# Convenience for cross-repo readers: the normalized form used for entity joins.
ACME_NORMALIZED = normalize_name("ACME CONSTRUCTION INC")
