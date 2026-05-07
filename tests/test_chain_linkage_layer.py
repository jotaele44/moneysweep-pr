"""Tests for Phase 5 chain linkage layer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from contract_sweeper.linkage.chain_linkage import (
    EXECUTION_CHAIN_MASTER_COLUMNS,
    EXECUTION_CHAIN_PER_ASSET_COLUMNS,
    build_execution_chain,
)
from contract_sweeper.linkage.linkage_runner import run_chain_linkage
from contract_sweeper.runtime.schema_registry import SchemaDefinition, SchemaRegistry


def _schema_registry() -> SchemaRegistry:
    return SchemaRegistry(
        version=1,
        datasets=[
            SchemaDefinition(
                name="execution_chain_master",
                format="csv",
                required_fields=["entity_id", "project_id", "funding_source", "source_system", "link_confidence"],
                optional_fields=["upstream_entity_id", "downstream_asset_id", "municipality"],
            )
        ],
    )


def _contracts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "project_id": "P-001",
                "funding_source": "usaspending_awards",
                "source_system": "usaspending_awards",
                "award_id": "A-001",
                "obligation_amount": "1000000",
                "agency": "USACE",
                "source_date": "2025-01-10",
                "geo_location": "San Juan, PR",
                "normalized_name": "ACME INFRASTRUCTURE LLC",
                "source_url": "https://example.test/a1",
            },
            {
                "entity_id": "anon-xyz",
                "project_id": "P-002",
                "funding_source": "fema_openfema",
                "source_system": "fema_openfema",
                "award_id": "A-002",
                "obligation_amount": "700000",
                "agency": "FEMA",
                "source_date": "2025-01-11",
                "geo_location": "Ponce, PR",
                "normalized_name": "ACME INFRASTRUCTURE LLC",
                "source_url": "https://example.test/a2",
            },
            {
                "entity_id": "",
                "project_id": "",
                "funding_source": "municipal_contracts",
                "source_system": "municipal_contracts",
                "award_id": "A-003",
                "obligation_amount": "250000",
                "agency": "Municipio de Caguas",
                "source_date": "2025-01-12",
                "geo_location": "Caguas, PR",
                "normalized_name": "UNKNOWN SERVICES GROUP",
                "source_url": "https://example.test/a3",
            },
        ]
    )


def _entities_resolved() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "parent_uei": "PARENT-ACME-001",
                "normalized_name": "ACME INFRASTRUCTURE LLC",
                "source_system": "usaspending_awards",
                "link_confidence": 0.98,
                "alias": "ACME INFRASTRUCTURE LLC",
                "canonical_name": "ACME INFRASTRUCTURE LLC",
            }
        ]
    )


def test_build_execution_chain_outputs_and_review_queue():
    result = build_execution_chain(
        contracts=_contracts(),
        resolved_entities=_entities_resolved(),
        review_threshold=0.85,
        linkage_target=0.9,
    )

    master = result.execution_chain_master
    assert not master.empty
    assert set(EXECUTION_CHAIN_MASTER_COLUMNS).issubset(set(master.columns))

    acme_rows = master[master["award_id"].isin(["A-001", "A-002"])]
    assert all(acme_rows["upstream_entity_id"] == "PARENT-ACME-001")
    assert all(acme_rows["link_confidence"] >= 0.85)

    queue = result.low_confidence_review_queue
    assert "A-003" in set(queue["award_id"])

    per_asset = result.execution_chain_per_asset
    assert not per_asset.empty
    assert set(EXECUTION_CHAIN_PER_ASSET_COLUMNS).issubset(set(per_asset.columns))


def test_run_chain_linkage_writes_artifacts_and_meets_target(tmp_path: Path):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    contracts = _contracts().iloc[:2].copy()
    contracts.to_csv(processed / "contracts_master.csv", index=False, encoding="utf-8")

    entities = _entities_resolved()
    entities.to_csv(processed / "entities_resolved.csv", index=False, encoding="utf-8")

    artifacts = run_chain_linkage(
        project_root=tmp_path,
        schema_registry=_schema_registry(),
        linkage_target=0.9,
        review_threshold=0.85,
    )

    assert artifacts.execution_chain_master_csv.exists()
    assert artifacts.execution_chain_per_asset_csv.exists()
    assert artifacts.low_confidence_review_queue_csv.exists()
    assert artifacts.summary_json.exists()

    summary = artifacts.summary
    assert summary["schema_validation_ok"] is True
    assert summary["cross_layer_linkage_rate"] >= 0.9
    assert summary["target_met"] is True
