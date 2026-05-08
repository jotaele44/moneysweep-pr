"""R0 production-status gate for report and graph-facing outputs.

This module evaluates lightweight production-readiness rules without changing
analytics logic. It stamps existing outputs as diagnostic/partial/validated
based on observable gate metrics.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATUS_NON_PRODUCTION = "NON_PRODUCTION_DIAGNOSTIC"
STATUS_PARTIAL = "PARTIAL_PRODUCTION"
STATUS_VALIDATED = "PRODUCTION_VALIDATED"

REPORT_SUMMARY = Path("data/reports/pr_report_summary.json")
REPORT_MARKDOWN = Path("data/reports/pr_investigative_report.md")
POWER_SUMMARY = Path("data/staging/processed/pr_power_network_summary.json")
DOMINANCE_SUMMARY = Path("data/staging/processed/dominance_summary.json")
GRAPH_SUMMARY = Path("data/staging/processed/graph/network_summary.json")
PRIME_SUB_SUMMARY = Path("data/staging/processed/pr_prime_sub_summary.json")
ENTITY_MASTER = Path("data/staging/processed/entity_master.csv")
ARTIFACT_AUDIT = Path("data/exports/output_validation_audit.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _safe_int(value: Any) -> int:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _non_empty_ratio(values: list[str]) -> float:
    if not values:
        return 0.0
    non_empty = sum(1 for v in values if str(v).strip())
    return round(non_empty / len(values), 4)


def _compute_parent_uei_coverage(root: Path) -> float:
    path = root / ENTITY_MASTER
    if not path.exists():
        return 0.0

    values: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            if "parent_uei" not in (reader.fieldnames or []):
                return 0.0
            for row in reader:
                values.append(str(row.get("parent_uei", "")))
    except OSError:
        return 0.0

    return _non_empty_ratio(values)


def _detect_fixture_or_synthetic(report_summary: dict[str, Any], prime_sub_summary: dict[str, Any]) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    unique_entities = _safe_int(report_summary.get("awards", {}).get("unique_entities"))
    total_ranked = _safe_int(report_summary.get("power_network", {}).get("total_ranked"))
    prime_count = _safe_int(prime_sub_summary.get("prime_count"))
    sub_count = _safe_int(prime_sub_summary.get("sub_count"))
    pair_count = _safe_int(prime_sub_summary.get("pair_count"))

    if unique_entities == 18:
        reasons.append("report unique_entities is exactly 18")
    if total_ranked == 18:
        reasons.append("power network total_ranked is exactly 18")
    if prime_count == 18 and sub_count == 18:
        reasons.append("prime/sub universes are both exactly 18")
    if prime_count > 0 and sub_count > 0:
        dense_score = pair_count / max(prime_count * sub_count, 1)
        if dense_score >= 0.75:
            reasons.append("prime-sub matrix appears implausibly dense")

    return bool(reasons), reasons


def collect_gate_metrics(root: Path) -> dict[str, Any]:
    report_summary = _read_json(root / REPORT_SUMMARY)
    power_summary = _read_json(root / POWER_SUMMARY)
    dominance_summary = _read_json(root / DOMINANCE_SUMMARY)
    prime_sub_summary = _read_json(root / PRIME_SUB_SUMMARY)
    artifact_audit = _read_json(root / ARTIFACT_AUDIT)

    production_gate = artifact_audit.get("production_gate", {}) if artifact_audit else {}
    fixture_flag = artifact_audit.get("fixture_or_synthetic_data_detected", None)
    fixture_reasons = artifact_audit.get("fixture_or_synthetic_reasons", []) if artifact_audit else []

    if fixture_flag is None:
        fixture_flag, detected = _detect_fixture_or_synthetic(report_summary, prime_sub_summary)
        fixture_reasons = detected

    metrics = {
        "data_layers_populated": _safe_int(report_summary.get("data_layers")),
        "unique_entities": _safe_int(
            report_summary.get("awards", {}).get("unique_entities")
            or power_summary.get("total_entities")
            or dominance_summary.get("unique_vendors")
        ),
        "bond_actor_count": _safe_int(
            report_summary.get("power_network", {}).get("bond_actors_count")
            or production_gate.get("bond_actor_count")
        ),
        "parent_uei_coverage": (
            _safe_float(production_gate.get("parent_uei_coverage"))
            if production_gate.get("parent_uei_coverage") is not None
            else _compute_parent_uei_coverage(root)
        ),
        "fixture_or_synthetic_data_detected": bool(fixture_flag),
        "fixture_or_synthetic_reasons": fixture_reasons,
    }
    return metrics


def evaluate_production_status(metrics: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    blockers: list[dict[str, Any]] = []
    status = STATUS_VALIDATED

    data_layers = _safe_int(metrics.get("data_layers_populated"))
    unique_entities = _safe_int(metrics.get("unique_entities"))
    bond_actor_count = _safe_int(metrics.get("bond_actor_count"))
    parent_uei_coverage = _safe_float(metrics.get("parent_uei_coverage"))
    fixture_detected = bool(metrics.get("fixture_or_synthetic_data_detected"))

    if data_layers < 8:
        blockers.append(
            {
                "metric": "data_layers_populated",
                "observed_value": data_layers,
                "required_gate": ">= 8",
                "severity": "BLOCKER",
                "reason": "insufficient populated report layers",
            }
        )
        status = STATUS_NON_PRODUCTION

    if unique_entities < 100:
        blockers.append(
            {
                "metric": "unique_entities",
                "observed_value": unique_entities,
                "required_gate": ">= 100",
                "severity": "BLOCKER",
                "reason": "entity universe is too small for production claims",
            }
        )
        status = STATUS_NON_PRODUCTION

    if fixture_detected:
        blockers.append(
            {
                "metric": "fixture_or_synthetic_data_detected",
                "observed_value": True,
                "required_gate": "False",
                "severity": "BLOCKER",
                "reason": "fixture or synthetic data signatures detected",
            }
        )
        status = STATUS_NON_PRODUCTION

    if status != STATUS_NON_PRODUCTION and bond_actor_count == 0:
        blockers.append(
            {
                "metric": "bond_actor_count",
                "observed_value": bond_actor_count,
                "required_gate": "> 0 for full production",
                "severity": "WARN",
                "reason": "bond actor layer absent; cap status at partial",
            }
        )
        status = STATUS_PARTIAL

    if status != STATUS_NON_PRODUCTION and parent_uei_coverage < 0.90:
        blockers.append(
            {
                "metric": "parent_uei_coverage",
                "observed_value": round(parent_uei_coverage, 4),
                "required_gate": ">= 0.90 for full production",
                "severity": "WARN",
                "reason": "parent UEI coverage below production threshold",
            }
        )
        status = STATUS_PARTIAL

    return status, blockers


def _status_message(status: str) -> str:
    if status == STATUS_NON_PRODUCTION:
        return "Diagnostic output only — not production-valid."
    if status == STATUS_PARTIAL:
        return "Partial production output — major layers still require validation."
    return "Production-validated output."


def load_current_status(root: Path) -> dict[str, Any]:
    """Load previously computed production status, with safe defaults."""
    payload = _read_json(Path(root) / "data" / "exports" / "production_status.json")
    status = payload.get("production_status")
    if status not in {STATUS_NON_PRODUCTION, STATUS_PARTIAL, STATUS_VALIDATED}:
        status = STATUS_NON_PRODUCTION
    message = payload.get("status_message") or payload.get("production_status_message") or _status_message(status)
    return {"production_status": status, "status_message": message}


def _write_outputs(root: Path, payload: dict[str, Any], blockers: list[dict[str, Any]]) -> None:
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"
    exports_dir.mkdir(parents=True, exist_ok=True)
    review_dir.mkdir(parents=True, exist_ok=True)

    status_path = exports_dir / "production_status.json"
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    blockers_path = review_dir / "production_blockers.csv"
    with blockers_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = ["metric", "observed_value", "required_gate", "severity", "reason"]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(blockers)


def _stamp_json(path: Path, status: str, generated_at: str, message: str, blocker_count: int) -> bool:
    payload = _read_json(path)
    if not payload:
        return False
    payload["production_status"] = status
    payload["production_status_generated_at"] = generated_at
    payload["production_status_message"] = message
    payload["production_blocker_count"] = blocker_count
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def _stamp_report(path: Path, status: str, message: str) -> bool:
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8", errors="replace")
    status_block = f"> Production Status: {status}\n> {message}\n\n"

    if text.startswith("> Production Status:"):
        lines = text.splitlines()
        i = 0
        while i < len(lines) and lines[i].startswith("> "):
            i += 1
        stripped_remainder = "\n".join(lines[i:]).lstrip("\n")
        new_text = status_block + stripped_remainder
    else:
        new_text = status_block + text

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
    return True


def _stamp_existing_outputs(root: Path, status: str, generated_at: str, message: str, blocker_count: int) -> dict[str, Any]:
    stamped_json = 0
    for rel in [REPORT_SUMMARY, POWER_SUMMARY, DOMINANCE_SUMMARY, GRAPH_SUMMARY, PRIME_SUB_SUMMARY]:
        if _stamp_json(root / rel, status, generated_at, message, blocker_count):
            stamped_json += 1

    report_stamped = _stamp_report(root / REPORT_MARKDOWN, status, message)
    return {"json_summaries_stamped": stamped_json, "report_stamped": report_stamped}


def run_gate(root: Path) -> dict[str, Any]:
    root = Path(root)
    metrics = collect_gate_metrics(root)
    status, blockers = evaluate_production_status(metrics)
    generated_at = _utc_now()
    message = _status_message(status)

    payload = {
        "generated_at": generated_at,
        "production_status": status,
        "status_message": message,
        "production_status_message": message,
        "metrics": metrics,
        "blocker_count": len(blockers),
        "blockers": blockers,
    }

    _write_outputs(root, payload, blockers)
    stamp_result = _stamp_existing_outputs(root, status, generated_at, message, len(blockers))
    payload["stamped_outputs"] = stamp_result

    # Keep a direct copy with stamped-output counts for convenient callers.
    status_path = root / "data" / "exports" / "production_status.json"
    status_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return payload
