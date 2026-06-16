"""Pipeline entrypoint for project-emergence alerts.

This module is intentionally fail-soft: it never raises into the main pipeline
unless a caller chooses to do so. Missing master outputs produce an empty alert
ledger and Spiderweb queue so --run-project-alerts cannot break normal runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .alert_router import DEFAULT_ALERT_DIR, route_alert_outputs
from .project_signal_detector import (
    ProjectSignalDetector,
    load_records_from_csv,
    load_records_from_jsonl,
)

MASTER_CANDIDATES = (
    "data/staging/processed/pr_all_awards_master.csv",
    "data/staging/processed/pr_contracts_master.csv",
    "data/staging/processed/financial_flows_master.jsonl",
)


def discover_master_outputs(root: str | Path) -> list[Path]:
    base = Path(root)
    return [base / rel for rel in MASTER_CANDIDATES if (base / rel).exists()]


def load_master_records(paths: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in paths:
        if path.suffix.lower() == ".csv":
            records.extend(load_records_from_csv(path))
        elif path.suffix.lower() == ".jsonl":
            records.extend(load_records_from_jsonl(path))
    return records


def run(root: str | Path, logger=None) -> dict[str, Any]:
    root_path = Path(root)
    alert_dir = root_path / DEFAULT_ALERT_DIR.relative_to(DEFAULT_ALERT_DIR.parents[3])
    try:
        master_paths = discover_master_outputs(root_path)
        if not master_paths:
            if logger:
                logger.warning(
                    "[Project alerts] No master outputs found; writing empty alert outputs."
                )
            result = route_alert_outputs([], alert_dir=alert_dir)
            result.update({"input_paths": [], "record_count": 0, "status": "no_inputs"})
            return result

        records = load_master_records(master_paths)
        events = ProjectSignalDetector().detect(records)
        result = route_alert_outputs(events, alert_dir=alert_dir)
        result.update(
            {
                "input_paths": [str(p) for p in master_paths],
                "record_count": len(records),
                "status": "ok",
            }
        )
        if logger:
            logger.info(
                "[Project alerts] Done — %s records scanned, %s alerts, %s Spiderweb packets.",
                len(records),
                result.get("event_count", 0),
                result.get("spiderweb_count", 0),
            )
        return result
    except Exception as exc:  # failsoft by design
        if logger:
            logger.warning("[Project alerts] Failed without aborting pipeline: %s", exc)
        alert_dir.mkdir(parents=True, exist_ok=True)
        failure_path = alert_dir / "project_alert_failure.json"
        payload = {"status": "failed", "error": str(exc)}
        failure_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return {"status": "failed", "error": str(exc), "failure_path": str(failure_path)}
