"""R4.6 backfill execution planning for required unified-master inputs.

Produces a non-fabrication execution plan for all required build_unified_master
inputs, sourced from the R4.5 manual queue.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _first_producer_script(raw: str) -> str:
    scripts = [part for part in str(raw).split("|") if part.strip()]
    if not scripts:
        return ""

    # Prefer actionable producer/download/build scripts over analytics readers.
    priority_prefixes = (
        "scripts/download_",
        "scripts/ingest_",
        "scripts/deduplicate_",
        "scripts/auto_download",
    )
    for prefix in priority_prefixes:
        for script in scripts:
            if script.startswith(prefix):
                return script
    return scripts[0]


def _command_for(expected_input: str, dataset_label: str, producer_script: str) -> str:
    if expected_input.startswith("data/staging/expansion/"):
        return "python run_all.py --only usaspending --force"

    script = producer_script or ""
    if script.startswith("scripts/download_"):
        return f"python {script} --force"
    if script.startswith("scripts/ingest_"):
        return f"python {script} --force"
    if script == "scripts/deduplicate_master.py":
        return "python scripts/deduplicate_master.py"

    # Contracts core is assembled from normalized expansion feeds.
    if expected_input.endswith("pr_contracts_master.csv"):
        return "python scripts/deduplicate_master.py"

    # Fallback command keeps this explicit and safe.
    return f"python {script}" if script else f"python run_all.py --rebuild-source {dataset_label}"


def _source_of_truth(expected_input: str, dataset_label: str) -> str:
    if expected_input.startswith("data/staging/expansion/"):
        return "USASpending expansion extracts (IDV/DoD/reconstruction windows)"

    map_by_dataset = {
        "contracts": "USASpending/FPDS normalized expansion files",
        "grants": "USASpending assistance/grants APIs",
        "subawards": "FSRS/Subawards feeds",
        "fema_pa": "OpenFEMA Public Assistance datasets",
        "fema_hmgp": "OpenFEMA HMGP datasets",
        "research": "Federal research award sources",
        "sba_loans": "SBA disaster/business loan datasets",
        "slfrf": "Treasury SLFRF recipient project files",
        "cdbg_dr": "HUD CDBG-DR / DRGR exports",
        "dot": "DOT award datasets",
        "usda": "USDA award datasets",
        "doe": "DOE award datasets",
        "hud": "HUD federal award datasets",
        "sbir": "SBIR/STTR award datasets",
        "epa": "EPA award datasets",
        "usace_civil": "USACE civil works award datasets",
        "wioa": "WIOA grants datasets",
    }
    return map_by_dataset.get(dataset_label, "Registered source datasets for this input")


def _acceptance_gate(expected_input: str) -> str:
    if expected_input.startswith("data/staging/expansion/"):
        return "file_exists AND rows>0 AND lineage_manifest_present AND window_coverage_verified"
    return "file_exists AND rows>0 AND canonical_columns_present AND lineage_manifest_present"


def _precheck(expected_input: str) -> str:
    if expected_input.endswith("pr_contracts_master.csv"):
        return "normalized_expansion_*.csv available in data/staging/processed"
    if expected_input.startswith("data/staging/expansion/"):
        return "USASpending credentials/config ready; extraction windows configured"
    return "raw/staging source files present OR downloader credentials configured"


def _plan_row(raw: dict[str, str]) -> dict[str, Any]:
    expected_input = raw.get("expected_input", "")
    dataset_label = raw.get("dataset_label", "")
    input_group = raw.get("input_group", "")
    producer_script = _first_producer_script(raw.get("producer_scripts", ""))

    return {
        "priority": int(raw.get("priority", "0") or 0),
        "expected_input": expected_input,
        "dataset_label": dataset_label,
        "input_group": input_group,
        "recommended_action": raw.get("recommended_action", ""),
        "source_of_truth": _source_of_truth(expected_input, dataset_label),
        "producer_script": producer_script,
        "producer_command": _command_for(expected_input, dataset_label, producer_script),
        "precheck_required": _precheck(expected_input),
        "acceptance_gate": _acceptance_gate(expected_input),
        "lineage_manifest_required": True,
        "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        "on_failure": "append_to_manual_source_download_queue_and_block_downstream",
        "output_path": expected_input,
    }


def _render_markdown(status: dict[str, Any], rows: list[dict[str, Any]]) -> str:
    lines = []
    lines.append("# R4.6 Backfill Execution Plan")
    lines.append("")
    lines.append(f"Generated: {status['generated_at']}")
    lines.append("")
    lines.append("## Guardrails")
    lines.append("")
    lines.append("- No fabricated/synthetic rows are allowed.")
    lines.append("- Only raw/staging/normalized/exports/runtime sources may be used for recovery planning.")
    lines.append("- Report/summary/graph/top-node artifacts are not valid data inputs.")
    lines.append("- Phase 7/8 remains blocked until recovery and downstream validation gates pass.")
    lines.append("")
    lines.append("## Inputs To Backfill")
    lines.append("")
    for row in sorted(rows, key=lambda r: int(r.get("priority", 0))):
        lines.append(f"### {row['priority']}. `{row['expected_input']}`")
        lines.append(f"- Dataset: `{row['dataset_label']}` ({row['input_group']})")
        lines.append(f"- Source of truth: {row['source_of_truth']}")
        lines.append(f"- Producer script: `{row['producer_script']}`")
        lines.append(f"- Command: `{row['producer_command']}`")
        lines.append(f"- Precheck: {row['precheck_required']}")
        lines.append(f"- Acceptance gate: {row['acceptance_gate']}")
        lines.append(f"- Fabrication policy: `{row['row_fabrication_policy']}`")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def run_plan(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    manual_queue_path = review_dir / "manual_source_download_queue.csv"
    manual_rows = _read_csv(manual_queue_path)

    plan_rows = [_plan_row(row) for row in manual_rows]
    plan_rows = sorted(plan_rows, key=lambda r: int(r.get("priority", 0)))

    csv_path = exports_dir / "backfill_execution_plan_r4_6.csv"
    md_path = exports_dir / "backfill_execution_plan_r4_6.md"

    _write_csv(
        csv_path,
        plan_rows,
        [
            "priority",
            "expected_input",
            "dataset_label",
            "input_group",
            "recommended_action",
            "source_of_truth",
            "producer_script",
            "producer_command",
            "precheck_required",
            "acceptance_gate",
            "lineage_manifest_required",
            "row_fabrication_policy",
            "on_failure",
            "output_path",
        ],
    )

    status = {
        "generated_at": _utc_now(),
        "plan_row_count": len(plan_rows),
        "expected_input_count": len(plan_rows),
        "manual_queue_source": str(manual_queue_path.relative_to(root)),
        "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
        "phase_7_8_blocked": True,
        "phase_7_8_block_reason": "R4.6 backfill planning active; gates for R5/R6 still required before Phase 7/8",
        "outputs": {
            "backfill_plan_csv": str(csv_path.relative_to(root)),
            "backfill_plan_md": str(md_path.relative_to(root)),
        },
    }

    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_render_markdown(status, plan_rows), encoding="utf-8")
    _write_json(exports_dir / "backfill_execution_plan_r4_6_status.json", status)

    prior_rebuild = _read_json(exports_dir / "rebuild_status.json")
    rebuild_status = dict(prior_rebuild)
    rebuild_status.update(
        {
            "r4_6_generated_at": status["generated_at"],
            "r4_6_plan_row_count": len(plan_rows),
            "r4_6_row_fabrication_policy": status["row_fabrication_policy"],
            "r4_6_gate_passed": bool(len(plan_rows) == 21),
            "phase_7_8_blocked": True,
            "phase_7_8_block_reason": status["phase_7_8_block_reason"],
            "r4_6_outputs": status["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status
