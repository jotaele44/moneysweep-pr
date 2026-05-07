"""Tests for Phase 4 entity resolution layer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from contract_sweeper.resolution.entity_resolution import ENTITIES_RESOLVED_COLUMNS, resolve_entities
from contract_sweeper.resolution.resolution_runner import run_entity_resolution


def _contracts_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "parent_uei": "PARENT-ACME-001",
                "normalized_name": "Acme Infrastructure LLC",
                "award_id": "A-1",
                "funding_source": "usaspending_awards",
                "obligation_amount": "1200000",
                "geo_location": "San Juan, PR",
                "project_id": "A-1",
                "agency": "USACE",
                "source_system": "usaspending_awards",
                "source_url": "",
                "source_date": "2025-01-10",
                "link_confidence": 0.98,
                "risk_score": 0.0,
            },
            {
                "entity_id": "anon-a1",
                "parent_uei": "",
                "normalized_name": "Acme Infrastructure L L C",
                "award_id": "A-2",
                "funding_source": "fema_openfema",
                "obligation_amount": "750000",
                "geo_location": "Ponce, PR",
                "project_id": "A-2",
                "agency": "FEMA",
                "source_system": "fema_openfema",
                "source_url": "",
                "source_date": "2025-01-12",
                "link_confidence": 0.72,
                "risk_score": 0.0,
            },
            {
                "entity_id": "anon-b1",
                "parent_uei": "",
                "normalized_name": "Beta Water Services",
                "award_id": "B-1",
                "funding_source": "prasa_aaa",
                "obligation_amount": "2100000",
                "geo_location": "Mayaguez, PR",
                "project_id": "B-1",
                "agency": "PRASA",
                "source_system": "prasa_aaa",
                "source_url": "",
                "source_date": "2025-01-13",
                "link_confidence": 0.63,
                "risk_score": 0.0,
            },
            {
                "entity_id": "UEI-GAMMA-001",
                "parent_uei": "",
                "normalized_name": "Gamma Energy Group",
                "award_id": "G-1",
                "funding_source": "prepa_luma_genera",
                "obligation_amount": "500000",
                "geo_location": "Arecibo, PR",
                "project_id": "G-1",
                "agency": "PREPA",
                "source_system": "prepa_luma_genera",
                "source_url": "",
                "source_date": "2025-01-14",
                "link_confidence": 0.9,
                "risk_score": 0.0,
            },
        ]
    )


def test_resolve_entities_parent_collapse_and_review_queue():
    result = resolve_entities(
        contracts=_contracts_df(),
        fuzzy_threshold_high=93.0,
        fuzzy_threshold_medium=88.0,
        review_threshold=0.85,
        high_value_threshold=1000000.0,
    )

    resolved = result.entities_resolved
    assert not resolved.empty
    assert set(ENTITIES_RESOLVED_COLUMNS).issubset(set(resolved.columns))

    acme_alias = resolved[resolved["alias"] == "ACME INFRASTRUCTURE L L C"].iloc[0]
    assert acme_alias["entity_id"] == "PARENT-ACME-001"
    assert acme_alias["link_confidence"] >= 0.85

    beta_alias = resolved[resolved["alias"] == "BETA WATER SERVICES"].iloc[0]
    assert beta_alias["resolved_from"] == "new_entity"

    low_conf = result.low_confidence_review_queue
    assert "BETA WATER SERVICES" in set(low_conf["alias"])

    high_value = result.high_value_unresolved_entities
    assert "BETA WATER SERVICES" in set(high_value["alias"])

    assert result.summary["aliases_total"] == 4
    assert result.summary["resolved_total"] >= 3


def test_run_entity_resolution_writes_artifacts(tmp_path: Path):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    contracts = _contracts_df()
    contracts.to_csv(processed / "contracts_master.csv", index=False, encoding="utf-8")

    artifacts = run_entity_resolution(
        project_root=tmp_path,
        review_threshold=0.85,
        fuzzy_threshold_high=93.0,
        fuzzy_threshold_medium=88.0,
        high_value_threshold=1000000.0,
    )

    assert artifacts.entities_resolved_csv.exists()
    assert artifacts.alias_registry_json.exists()
    assert artifacts.low_confidence_review_queue_csv.exists()
    assert artifacts.high_value_unresolved_csv.exists()
    assert artifacts.summary_json.exists()

    out_df = pd.read_csv(artifacts.entities_resolved_csv)
    assert "entity_id" in out_df.columns
    assert "parent_uei" in out_df.columns
    assert "normalized_name" in out_df.columns
    assert "source_system" in out_df.columns
    assert "link_confidence" in out_df.columns


def test_resolve_entities_empty_input():
    empty = pd.DataFrame(columns=["entity_id", "parent_uei", "normalized_name", "source_system", "obligation_amount"])
    result = resolve_entities(empty)

    assert result.entities_resolved.empty
    assert result.low_confidence_review_queue.empty
    assert result.summary["aliases_total"] == 0
