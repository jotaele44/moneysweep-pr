"""Runner for Phase 6 financial flow artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .financial_flows import FinancialFlowResult, build_financial_flows


@dataclass(frozen=True)
class FinancialFlowArtifacts:
    """Filesystem outputs from a financial flow run."""

    financial_flows_master_parquet: Path
    financial_flows_master_csv: Path
    summary_json: Path
    summary: dict[str, Any]


def _load_execution_chain(project_root: Path, input_path: Path | None = None) -> pd.DataFrame:
    path = input_path or project_root / "data" / "staging" / "processed" / "execution_chain_master.csv"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, dtype=str, low_memory=False)


def run_financial_flows(project_root: Path, input_path: Path | None = None) -> FinancialFlowArtifacts:
    """Build and write financial flow master outputs."""

    processed_dir = project_root / "data" / "staging" / "processed"
    reports_dir = project_root / "data" / "reports"
    processed_dir.mkdir(parents=True, exist_ok=True)
    reports_dir.mkdir(parents=True, exist_ok=True)

    execution_chain = _load_execution_chain(project_root, input_path=input_path)
    result: FinancialFlowResult = build_financial_flows(execution_chain)

    parquet_path = processed_dir / "financial_flows_master.parquet"
    csv_path = processed_dir / "financial_flows_master.csv"
    summary_path = reports_dir / "financial_flows_summary.json"

    result.financial_flows_master.to_parquet(parquet_path, index=False)
    result.financial_flows_master.to_csv(csv_path, index=False, encoding="utf-8")
    summary_path.write_text(json.dumps(result.summary, indent=2, sort_keys=True), encoding="utf-8")

    return FinancialFlowArtifacts(
        financial_flows_master_parquet=parquet_path,
        financial_flows_master_csv=csv_path,
        summary_json=summary_path,
        summary=result.summary,
    )
