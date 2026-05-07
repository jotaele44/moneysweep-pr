"""Tests for Phase 7 risk signal engine."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from contract_sweeper.risk.notifiers import notify_alerts
from contract_sweeper.risk.risk_runner import run_risk_signal_engine
from contract_sweeper.risk.risk_signal_engine import (
    DEFINITIVE_TERMS,
    RISK_ALERT_COLUMNS,
    RISK_REVIEW_COLUMNS,
    assert_probabilistic_alert_language,
    build_risk_signals,
)
from contract_sweeper.runtime.schema_registry import SchemaDefinition, SchemaRegistry


def _schema_registry() -> SchemaRegistry:
    return SchemaRegistry(
        version=1,
        datasets=[
            SchemaDefinition(
                name="risk_alerts_master",
                format="csv",
                required_fields=[
                    "alert_id",
                    "alert_type",
                    "indicator_label",
                    "entity_id",
                    "project_id",
                    "source_system",
                    "risk_score",
                    "probabilistic_assessment",
                ],
                optional_fields=[],
            )
        ],
    )


def _contracts() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "parent_uei": "PARENT-ACME-001",
                "normalized_name": "ACME WATER EMERGENCY SERVICES",
                "award_id": "A-001",
                "funding_source": "fema_openfema",
                "obligation_amount": "2500000",
                "geo_location": "San Juan, PR",
                "municipality": "San Juan",
                "project_id": "P-001",
                "agency": "FEMA",
                "source_system": "fema_openfema",
                "source_url": "https://example.test/a1",
                "source_date": "2025-01-10",
                "link_confidence": "0.62",
                "risk_score": "0.5",
                "contract_type": "emergency water repair",
            }
        ]
    )


def _execution_chain() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "project_id": "P-001",
                "funding_source": "fema_openfema",
                "source_system": "fema_openfema",
                "link_confidence": "0.70",
                "upstream_entity_id": "PARENT-ACME-001",
                "downstream_asset_id": "asset:water:001",
                "municipality": "San Juan",
                "award_id": "A-001",
                "obligation_amount": "2500000",
                "agency": "FEMA",
                "source_date": "2025-01-10",
                "evidence_path": "https://example.test/a1",
            }
        ]
    )


def _entities() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "parent_uei": "PARENT-ACME-001",
                "normalized_name": "ACME WATER EMERGENCY SERVICES",
                "source_system": "sam",
                "link_confidence": "0.98",
            }
        ]
    )


def _financial_flows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "flow_id": "flow-001",
                "flow_type": "recovery_execution",
                "source_system": "fema_openfema",
                "funding_source": "fema_openfema",
                "award_id": "A-000",
                "project_id": "P-000",
                "entity_id": "UEI-ACME-001",
                "upstream_entity_id": "PARENT-ACME-001",
                "downstream_asset_id": "asset:water:000",
                "municipality": "San Juan",
                "amount_type": "obligation_amount",
                "amount": "500000",
                "flow_date": "2024-01-10",
                "link_confidence": "0.92",
                "evidence_path": "https://example.test/a0",
            },
            {
                "flow_id": "flow-002",
                "flow_type": "recovery_execution",
                "source_system": "fema_openfema",
                "funding_source": "fema_openfema",
                "award_id": "A-001",
                "project_id": "P-001",
                "entity_id": "UEI-ACME-001",
                "upstream_entity_id": "PARENT-ACME-001",
                "downstream_asset_id": "asset:water:001",
                "municipality": "San Juan",
                "amount_type": "obligation_amount",
                "amount": "2500000",
                "flow_date": "2025-01-10",
                "link_confidence": "0.70",
                "evidence_path": "https://example.test/a1",
            },
        ]
    )


def _keywords() -> dict[str, list[str]]:
    return {
        "procurement_pressure": ["emergency", "urgent"],
        "asset_exposure": ["water", "power"],
    }


def _rules() -> dict[str, float]:
    return {
        "high_value_threshold": 1000000,
        "low_confidence_threshold": 0.75,
        "differential_change_multiplier": 2.0,
        "review_threshold": 0.65,
    }


def _critical_assets() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"asset_category": "water", "asset_keyword": "water", "criticality": "high", "notes": ""},
            {"asset_category": "energy", "asset_keyword": "power", "criticality": "high", "notes": ""},
        ]
    )


def _lobbying() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "entity_id": "UEI-ACME-001",
                "normalized_name": "ACME WATER EMERGENCY SERVICES",
                "source_system": "cabilderos",
                "evidence_path": "https://example.test/lobby",
            }
        ]
    )


def test_build_risk_signals_uses_probabilistic_language():
    result = build_risk_signals(
        contracts_master=_contracts(),
        execution_chain_master=_execution_chain(),
        entities_resolved=_entities(),
        financial_flows_master=_financial_flows(),
        keywords=_keywords(),
        rules=_rules(),
        critical_assets=_critical_assets(),
        lobbying_tables=_lobbying(),
    )

    alerts = result.risk_alerts_master
    assert not alerts.empty
    assert set(RISK_ALERT_COLUMNS).issubset(set(alerts.columns))
    assert "possible_differential_change_event" in set(alerts["alert_type"])
    assert "possible_influence_context_overlap" in set(alerts["alert_type"])
    assert result.high_risk_projects_geojson["type"] == "FeatureCollection"
    assert result.summary["probabilistic_language_ok"] is True

    combined_text = " ".join(
        alerts[col].fillna("").astype(str).str.lower().str.cat(sep=" ")
        for col in ["alert_type", "indicator_label", "probabilistic_assessment", "recommended_review_action"]
    )
    assert not any(term in combined_text for term in DEFINITIVE_TERMS)
    assert_probabilistic_alert_language(alerts)


def test_risk_review_queue_collects_reviewable_alerts():
    result = build_risk_signals(
        contracts_master=_contracts(),
        execution_chain_master=_execution_chain(),
        entities_resolved=_entities(),
        financial_flows_master=_financial_flows(),
        keywords=_keywords(),
        rules=_rules(),
        critical_assets=_critical_assets(),
    )

    queue = result.risk_review_queue
    assert not queue.empty
    assert set(RISK_REVIEW_COLUMNS).issubset(set(queue.columns))
    assert set(queue["alert_id"]).issubset(set(result.risk_alerts_master["alert_id"]))


def test_notifier_is_local_only_by_default():
    summary = notify_alerts(pd.DataFrame([{"alert_id": "risk-001"}]), env={})

    assert summary["mode"] == "local_only"
    assert summary["external_notifications_enabled"] is False
    assert summary["notifications_sent"] == 0


def test_run_risk_signal_engine_writes_artifacts(tmp_path: Path):
    processed = tmp_path / "data" / "staging" / "processed"
    risk_dir = tmp_path / "contract_sweeper" / "risk"
    processed.mkdir(parents=True, exist_ok=True)
    risk_dir.mkdir(parents=True, exist_ok=True)

    _contracts().to_parquet(processed / "contracts_master.parquet", index=False)
    _execution_chain().to_csv(processed / "execution_chain_master.csv", index=False)
    _entities().to_csv(processed / "entities_resolved.csv", index=False)
    _financial_flows().to_parquet(processed / "financial_flows_master.parquet", index=False)
    (risk_dir / "risk_keywords.yaml").write_text("procurement_pressure:\n  - emergency\n", encoding="utf-8")
    (risk_dir / "alert_rules.yaml").write_text(
        "high_value_threshold: 1000000\nlow_confidence_threshold: 0.75\nreview_threshold: 0.65\n",
        encoding="utf-8",
    )
    _critical_assets().to_csv(risk_dir / "critical_asset_registry.csv", index=False)

    artifacts = run_risk_signal_engine(project_root=tmp_path, schema_registry=_schema_registry())

    assert artifacts.risk_alerts_master_csv.exists()
    assert artifacts.high_risk_projects_geojson.exists()
    assert artifacts.entity_behavior_history_parquet.exists()
    assert artifacts.risk_review_queue_csv.exists()
    assert artifacts.summary_json.exists()
    assert artifacts.summary["schema_validation_ok"] is True
    assert artifacts.summary["notifier"]["mode"] == "local_only"
