"""Tests for Phase 6 financial flow layer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from contract_sweeper.flows.financial_flows import FINANCIAL_FLOW_COLUMNS, build_financial_flows
from contract_sweeper.flows.flows_runner import run_financial_flows


def _execution_chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "project_id": "P-001",
                "funding_source": "fema_openfema",
                "source_system": "fema_openfema",
                "link_confidence": 0.94,
                "upstream_entity_id": "PARENT-ACME-001",
                "downstream_asset_id": "asset:recovery:001",
                "municipality": "San Juan",
                "award_id": "A-001",
                "obligation_amount": "1000000",
                "agency": "FEMA",
                "source_date": "2025-01-10",
                "evidence_path": "https://example.test/a1",
            },
            {
                "entity_id": "UEI-WATER-001",
                "project_id": "P-002",
                "funding_source": "prasa_aaa",
                "source_system": "prasa_aaa",
                "link_confidence": 0.91,
                "upstream_entity_id": "PARENT-WATER-001",
                "downstream_asset_id": "asset:water:002",
                "municipality": "Ponce",
                "award_id": "A-002",
                "obligation_amount": "250000",
                "agency": "PRASA",
                "source_date": "2025-01-11",
                "evidence_path": "local://prasa",
            },
        ]
    )


def test_build_financial_flows_from_execution_chain():
    result = build_financial_flows(_execution_chain())

    flows = result.financial_flows_master
    assert len(flows) == 2
    assert set(FINANCIAL_FLOW_COLUMNS).issubset(set(flows.columns))
    assert result.summary["rows_total"] == 2
    assert result.summary["total_amount"] == 1250000.0
    assert "recovery_execution" in set(flows["flow_type"])
    assert "water_infrastructure_execution" in set(flows["flow_type"])


def test_run_financial_flows_writes_parquet_and_csv(tmp_path: Path):
    processed = tmp_path / "data" / "staging" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    _execution_chain().to_csv(processed / "execution_chain_master.csv", index=False)

    artifacts = run_financial_flows(project_root=tmp_path)

    assert artifacts.financial_flows_master_parquet.exists()
    assert artifacts.financial_flows_master_csv.exists()
    assert artifacts.summary_json.exists()

    parquet_df = pd.read_parquet(artifacts.financial_flows_master_parquet)
    csv_df = pd.read_csv(artifacts.financial_flows_master_csv)
    assert len(parquet_df) == 2
    assert len(csv_df) == 2
