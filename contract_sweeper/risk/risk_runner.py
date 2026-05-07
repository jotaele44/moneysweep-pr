"""Runner for Phase 7 risk signal artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from contract_sweeper.risk.notifiers import notify_alerts
from contract_sweeper.risk.risk_signal_engine import RiskSignalResult, build_risk_signals
from contract_sweeper.runtime.schema_registry import SchemaRegistry
from contract_sweeper.runtime.validation import validate_required_fields


@dataclass(frozen=True)
class RiskRunArtifacts:
    """Filesystem outputs from a risk signal engine run."""

    risk_alerts_master_csv: Path
    high_risk_projects_geojson: Path
    entity_behavior_history_parquet: Path
    risk_review_queue_csv: Path
    summary_json: Path
    summary: dict[str, Any]


def _load_tabular(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path, dtype=str, low_memory=False)


def _load_contracts(project_root: Path, path: Path | None = None) -> pd.DataFrame:
    if path is not None:
        return _load_tabular(path)
    processed = project_root / "data" / "staging" / "processed"
    parquet_path = processed / "contracts_master.parquet"
    csv_path = processed / "contracts_master.csv"
    return _load_tabular(parquet_path if parquet_path.exists() else csv_path)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _load_critical_assets(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, low_memory=False)


def _risk_alert_required_fields(schema_registry: SchemaRegistry) -> list[str]:
    for dataset in schema_registry.datasets:
        if dataset.name == "risk_alerts_master":
            return dataset.required_fields
    return ["alert_id", "alert_type", "entity_id", "risk_score", "probabilistic_assessment"]


def run_risk_signal_engine(
    project_root: Path,
    schema_registry: SchemaRegistry,
    contracts_path: Path | None = None,
    execution_chain_path: Path | None = None,
    entities_resolved_path: Path | None = None,
    financial_flows_path: Path | None = None,
    asset_control_graph_path: Path | None = None,
    lobbying_tables_path: Path | None = None,
    keywords_path: Path | None = None,
    rules_path: Path | None = None,
    critical_assets_path: Path | None = None,
) -> RiskRunArtifacts:
    """Run risk signal engine and write Phase 7 artifacts."""

    processed_dir = project_root / "data" / "staging" / "processed"
    reports_dir = project_root / "data" / "reports"
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    contracts = _load_contracts(project_root, path=contracts_path)
    execution_chain = _load_tabular(execution_chain_path or processed_dir / "execution_chain_master.csv")
    entities_resolved = _load_tabular(entities_resolved_path or processed_dir / "entities_resolved.csv")
    financial_flows = _load_tabular(financial_flows_path or processed_dir / "financial_flows_master.parquet")
    asset_control_graph = _load_tabular(asset_control_graph_path) if asset_control_graph_path is not None else pd.DataFrame()
    lobbying_tables = _load_tabular(lobbying_tables_path) if lobbying_tables_path is not None else pd.DataFrame()

    risk_dir = project_root / "contract_sweeper" / "risk"
    keywords = _load_yaml(keywords_path or risk_dir / "risk_keywords.yaml")
    rules = _load_yaml(rules_path or risk_dir / "alert_rules.yaml")
    critical_assets = _load_critical_assets(critical_assets_path or risk_dir / "critical_asset_registry.csv")

    result: RiskSignalResult = build_risk_signals(
        contracts_master=contracts,
        execution_chain_master=execution_chain,
        entities_resolved=entities_resolved,
        financial_flows_master=financial_flows,
        keywords=keywords,
        rules=rules,
        critical_assets=critical_assets,
        asset_control_graph_outputs=asset_control_graph,
        lobbying_tables=lobbying_tables,
    )

    required_fields = _risk_alert_required_fields(schema_registry)
    validation = validate_required_fields(
        result.risk_alerts_master.to_dict(orient="records"),
        required_fields,
    )

    risk_alerts_csv = processed_dir / "risk_alerts_master.csv"
    geojson_path = processed_dir / "high_risk_projects.geojson"
    behavior_parquet = processed_dir / "entity_behavior_history.parquet"
    review_queue_csv = processed_dir / "risk_review_queue.csv"
    summary_json = reports_dir / "risk_signal_summary.json"

    result.risk_alerts_master.to_csv(risk_alerts_csv, index=False, encoding="utf-8")
    geojson_path.write_text(json.dumps(result.high_risk_projects_geojson, indent=2, sort_keys=True), encoding="utf-8")
    result.entity_behavior_history.to_parquet(behavior_parquet, index=False)
    result.risk_review_queue.to_csv(review_queue_csv, index=False, encoding="utf-8")

    notifier_summary = notify_alerts(result.risk_alerts_master)
    summary = {**result.summary}
    summary.update(
        {
            "schema_required_fields": required_fields,
            "schema_validation_ok": bool(validation.ok),
            "schema_missing_required_fields": validation.missing_fields,
            "schema_field_completeness": validation.completeness,
            "notifier": notifier_summary,
        }
    )
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    return RiskRunArtifacts(
        risk_alerts_master_csv=risk_alerts_csv,
        high_risk_projects_geojson=geojson_path,
        entity_behavior_history_parquet=behavior_parquet,
        risk_review_queue_csv=review_queue_csv,
        summary_json=summary_json,
        summary=summary,
    )
