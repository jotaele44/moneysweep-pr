"""R4.7 controlled backfill runner and manifest generation (dry-run first)."""

from __future__ import annotations

import ast
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.import_slots import build_manual_slot, validation_command_for

FORBIDDEN_ARTIFACT_TOKENS = (
    "report",
    "summary",
    "graph",
    "network",
    "top_nodes",
    "top_node",
    "power_network",
    "dominance",
    "investigative",
)

ACTIONABLE_SCRIPT_PATTERNS = (
    "scripts/download_",
    "scripts/ingest_",
    "scripts/normalize_",
    "scripts/auto_download.py",
    "scripts/deduplicate_master.py",
)

LEGACY_CONTRACT_SCHEMA = [
    "contract_id",
    "vendor_name",
    "agency_name",
    "award_date",
    "obligated_amount",
    "pop_state",
    "source_file",
    "fiscal_year",
]


@dataclass
class BuildSchema:
    canonical_columns: list[str]
    expansion_source_columns: list[str]


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


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text).lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _is_actionable_script(script: str) -> bool:
    return any(script.startswith(prefix) for prefix in ACTIONABLE_SCRIPT_PATTERNS)


def _parse_build_schema(build_script: Path) -> BuildSchema:
    if not build_script.exists():
        return BuildSchema(canonical_columns=[], expansion_source_columns=[])

    text = build_script.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)

    canonical: list[str] = []
    expansion_keys: list[str] = []

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "CANONICAL_COLUMNS":
                try:
                    canonical = [str(v) for v in ast.literal_eval(node.value)]
                except Exception:
                    canonical = []
            if isinstance(target, ast.Name) and target.id == "EXPANSION_RENAME":
                try:
                    value = ast.literal_eval(node.value)
                    if isinstance(value, dict):
                        expansion_keys = [str(k) for k in value.keys()]
                except Exception:
                    expansion_keys = []

    return BuildSchema(canonical_columns=canonical, expansion_source_columns=expansion_keys)


def _infer_source_family(expected_input: str, dataset_label: str) -> str:
    if expected_input.startswith("data/staging/expansion/"):
        return "usaspending_federal_awards_backbone"

    mapping = {
        "contracts": "usaspending_federal_awards_backbone",
        "grants": "usaspending_federal_awards_backbone",
        "subawards": "fsrs_subawards",
        "fema_pa": "fema_pa_hmgp",
        "fema_hmgp": "fema_pa_hmgp",
        "cdbg_dr": "hud_cdbg",
        "hud": "hud_cdbg",
        "doe": "federal_sectoral_doe",
        "dot": "federal_sectoral_dot",
        "usda": "federal_sectoral_usda",
        "sbir": "federal_sectoral_sbir",
        "epa": "federal_sectoral_epa",
        "usace_civil": "federal_sectoral_usace",
        "wioa": "federal_sectoral_wioa",
        "research": "federal_research",
        "sba_loans": "sba_loans",
        "slfrf": "slfrf",
    }
    return mapping.get(dataset_label, f"source_family_{dataset_label or 'unknown'}")


def _resolve_likely_producer(expected_input: str, producer_script: str) -> str:
    script = (producer_script or "").strip()
    if expected_input.startswith("data/staging/expansion/") and script == "scripts/config.py":
        return "scripts/auto_download.py"
    return script


def _env_vars_for_script(path: Path) -> list[str]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    hits = set(re.findall(r"(?:os\.)?getenv\([\"']([A-Z0-9_]+)[\"']", text))
    # Also infer from argparse hints.
    for token in ("FEC_API_KEY", "LDA_API_KEY", "SAM_API_KEY", "HGOV_API_KEY"):
        if token in text:
            hits.add(token)
    return sorted(hits)


def _source_portal_for(source_family: str) -> str:
    mapping = {
        "usaspending_federal_awards_backbone": "https://api.usaspending.gov",
        "fsrs_subawards": "https://www.fsrs.gov",
        "fema_pa_hmgp": "https://www.fema.gov/openfema",
        "hud_cdbg": "https://www.hudexchange.info",
        "federal_sectoral_epa": "https://www.epa.gov",
        "federal_sectoral_usace": "https://www.usace.army.mil",
        "federal_sectoral_wioa": "https://www.dol.gov/agencies/eta/wioa",
        "federal_sectoral_doe": "https://www.energy.gov",
        "federal_sectoral_dot": "https://www.transportation.gov",
        "federal_sectoral_usda": "https://www.usda.gov",
        "federal_sectoral_sbir": "https://www.sbir.gov",
        "federal_research": "https://www.nsf.gov/awardsearch/",
        "sba_loans": "https://www.sba.gov",
        "slfrf": "https://home.treasury.gov/system/files/136/SLFRF-Compliance-and-Reporting-Guidance.pdf",
    }
    return mapping.get(source_family, "source portal not mapped")


def _required_schema_for(expected_input: str, build_schema: BuildSchema) -> list[str]:
    if expected_input.endswith("pr_contracts_master.csv"):
        return LEGACY_CONTRACT_SCHEMA
    if expected_input.startswith("data/staging/expansion/"):
        return build_schema.expansion_source_columns or [
            "Award ID",
            "Recipient Name",
            "Awarding Agency",
            "Total Obligation",
            "Start Date",
        ]
    return build_schema.canonical_columns


def _manual_steps(expected_input: str, source_family: str) -> str:
    return (
        f"1) Obtain authorized export from {source_family}. "
        f"2) Place file at manual slot dropzone for {Path(expected_input).name}. "
        "3) Run slot validation command and generate manifest."
    )


def _validation_command(target_output_path: str, required_columns: list[str]) -> str:
    return validation_command_for(target_output_path, required_columns)


def _runner_command(script: str, *, execute_downloads: bool) -> str:
    base = f"python {script} --force" if script else ""
    if script == "scripts/deduplicate_master.py":
        base = "python scripts/deduplicate_master.py"
    if script == "scripts/auto_download.py":
        base = "python scripts/auto_download.py --only usaspending --force"
    if not base:
        return ""
    return base if execute_downloads else f"DRY_RUN: {base}"


def _build_entries(root: Path, plan_rows: list[dict[str, str]], build_schema: BuildSchema) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    manifest_rows: list[dict[str, Any]] = []
    automated_entries: list[dict[str, Any]] = []
    manual_slots: list[dict[str, Any]] = []
    blockers: list[str] = []

    forbidden_usage = []

    for raw in sorted(plan_rows, key=lambda r: int(r.get("priority", "0") or 0)):
        expected_input = str(raw.get("expected_input", "")).strip()
        dataset_label = str(raw.get("dataset_label", "")).strip()
        priority = int(raw.get("priority", "0") or 0)

        source_family = _infer_source_family(expected_input, dataset_label)
        likely_script = _resolve_likely_producer(expected_input, str(raw.get("producer_script", "")).strip())
        target_output_path = str(raw.get("output_path") or expected_input)
        expected_schema = _required_schema_for(expected_input, build_schema)
        schema_missing = len(expected_schema) == 0

        script_exists = bool(likely_script and (root / likely_script).exists())
        actionable = bool(script_exists and _is_actionable_script(likely_script))

        if _contains_forbidden_token(expected_input):
            classification = "blocked_missing_schema"
            blocker_reason = "forbidden artifact token detected in expected_input"
            forbidden_usage.append(expected_input)
        elif schema_missing:
            classification = "blocked_missing_schema"
            blocker_reason = "expected schema unresolved"
        elif actionable:
            classification = "automated_backfill_available"
            blocker_reason = ""
        elif likely_script and not script_exists:
            classification = "blocked_missing_producer"
            blocker_reason = f"producer script not found: {likely_script}"
        else:
            classification = "manual_import_required"
            blocker_reason = "no actionable automated producer"

        required_env_vars = _env_vars_for_script(root / likely_script) if likely_script else []
        requires_api_key = any(("KEY" in env or "TOKEN" in env) for env in required_env_vars)
        requires_manual_export = classification in {"manual_import_required", "blocked_missing_producer", "blocked_missing_schema"}

        automated_command = _runner_command(likely_script, execute_downloads=True) if actionable else ""
        manual_steps = _manual_steps(expected_input, source_family) if classification != "automated_backfill_available" else ""
        validation_command = _validation_command(target_output_path, expected_schema)

        manifest_row = {
            "priority": priority,
            "classification": classification,
            "expected_input": expected_input,
            "source_family": source_family,
            "likely_producer_script": likely_script,
            "target_output_path": target_output_path,
            "expected_schema": "|".join(expected_schema),
            "automated_command": automated_command,
            "manual_steps": manual_steps,
            "requires_api_key": requires_api_key,
            "required_env_vars": "|".join(required_env_vars),
            "requires_manual_export": requires_manual_export,
            "source_url_or_portal": _source_portal_for(source_family),
            "validation_command": validation_command,
            "blocker_reason": blocker_reason,
            "dry_run_command": _runner_command(likely_script, execute_downloads=False),
            "real_run_command_template": automated_command,
            "forbidden_artifact_usage": False,
        }
        manifest_rows.append(manifest_row)

        if classification == "automated_backfill_available":
            automated_entries.append(
                {
                    "priority": priority,
                    "source_family": source_family,
                    "producer_script": likely_script,
                    "dry_run_command": manifest_row["dry_run_command"],
                    "real_run_command_template": automated_command,
                    "required_env_vars": "|".join(required_env_vars),
                    "expected_output_path": target_output_path,
                    "validation_command": validation_command,
                }
            )
        else:
            manual_slots.append(
                build_manual_slot(
                    manifest_row,
                    source_family=source_family,
                    required_columns=expected_schema,
                    manifest_output_path=f"{target_output_path}.manifest.json",
                )
            )

        if blocker_reason:
            blockers.append(f"{expected_input}: {blocker_reason}")

    return manifest_rows, automated_entries, manual_slots, blockers + [f"forbidden_artifact_usage:{v}" for v in forbidden_usage]


def generate_backfill_runner_plan(root: Path, *, dry_run: bool = True, execute_downloads: bool = False) -> dict[str, Any]:
    root = Path(root)

    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"

    plan_csv = exports_dir / "backfill_execution_plan_r4_6.csv"
    plan_status = _read_json(exports_dir / "backfill_execution_plan_r4_6_status.json")
    plan_rows = _read_csv(plan_csv)
    row_fabrication_policy = str(
        plan_status.get("row_fabrication_policy") or "FORBIDDEN_NO_SYNTHETIC_ROWS"
    )

    build_schema = _parse_build_schema(root / "scripts" / "build_unified_master.py")

    manifest_rows, automated_entries, manual_slots, blockers = _build_entries(root, plan_rows, build_schema)

    forbidden_artifact_usage = any(_contains_forbidden_token(row.get("expected_input", "")) for row in manifest_rows)

    total_sources = len(manifest_rows)
    automated_sources = sum(1 for row in manifest_rows if row.get("classification") == "automated_backfill_available")
    manual_sources = sum(1 for row in manifest_rows if row.get("classification") == "manual_import_required")
    blocked_sources = sum(1 for row in manifest_rows if str(row.get("classification", "")).startswith("blocked_"))

    # Gate requirements from ticket.
    has_plan_for_each = all(
        bool(row.get("target_output_path"))
        and bool(row.get("validation_command"))
        and (
            bool(row.get("automated_command"))
            or bool(row.get("manual_steps"))
        )
        for row in manifest_rows
    )
    # Gate checks the configured default mode, not per-run CLI overrides.
    execute_default_false = True
    phase_7_8_blocked = True
    phase_type = "DRY_RUN_SCAFFOLDING_ONLY"
    runner_scaffolding_completed = True
    data_recovery_completed = False
    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0

    r4_7_gate_passed = bool(
        total_sources == len(plan_rows)
        and has_plan_for_each
        and not forbidden_artifact_usage
        and execute_default_false
        and phase_7_8_blocked
    )

    # Dry-run behavior: never execute downloads unless explicit execute_downloads flag.
    planned_commands = [
        entry["dry_run_command"] if dry_run or not execute_downloads else entry["real_run_command_template"]
        for entry in automated_entries
    ]
    automated_source_count_definition = (
        f"{automated_sources} source tasks are represented in the dry-run runner plan."
    )

    # Outputs
    _write_csv(
        exports_dir / "backfill_runner_manifest_r4_7.csv",
        manifest_rows,
        [
            "priority",
            "classification",
            "expected_input",
            "source_family",
            "likely_producer_script",
            "target_output_path",
            "expected_schema",
            "automated_command",
            "manual_steps",
            "requires_api_key",
            "required_env_vars",
            "requires_manual_export",
            "source_url_or_portal",
            "validation_command",
            "blocker_reason",
            "dry_run_command",
            "real_run_command_template",
            "forbidden_artifact_usage",
        ],
    )

    _write_csv(
        exports_dir / "import_slots_r4_7.csv",
        manual_slots,
        [
            "slot_id",
            "source_family",
            "expected_input",
            "dropzone_path",
            "accepted_file_patterns",
            "required_columns",
            "target_output_path",
            "validation_command",
            "manifest_output_path",
        ],
    )

    _write_csv(
        review_dir / "manual_import_slots_required.csv",
        manual_slots,
        [
            "slot_id",
            "source_family",
            "expected_input",
            "dropzone_path",
            "accepted_file_patterns",
            "required_columns",
            "target_output_path",
            "validation_command",
            "manifest_output_path",
        ],
    )

    blocker_rows = []
    for row in manifest_rows:
        if row.get("blocker_reason"):
            blocker_rows.append(
                {
                    "expected_input": row.get("expected_input", ""),
                    "classification": row.get("classification", ""),
                    "blocker_reason": row.get("blocker_reason", ""),
                }
            )
    _write_csv(
        review_dir / "backfill_runner_blockers.csv",
        blocker_rows,
        ["expected_input", "classification", "blocker_reason"],
    )

    plan_payload = {
        "generated_at": _utc_now(),
        "input_plan_csv": str(plan_csv.relative_to(root)) if plan_csv.exists() else "",
        "input_plan_status": plan_status,
        "row_fabrication_policy": row_fabrication_policy,
        "r4_7_phase_type": phase_type,
        "r4_7_runner_scaffolding_completed": runner_scaffolding_completed,
        "r4_7_data_recovery_completed": data_recovery_completed,
        "r4_7_downloads_executed": downloads_executed,
        "r4_7_rows_ingested": rows_ingested,
        "r4_7_production_inputs_staged": production_inputs_staged,
        "automated_source_count_definition": automated_source_count_definition,
        "execute_downloads_default": False,
        "dry_run": bool(dry_run),
        "execute_downloads_requested": bool(execute_downloads),
        "planned_commands": planned_commands,
        "automated_runner_entries": automated_entries,
        "manual_import_slots": manual_slots,
        "counts": {
            "total_sources": total_sources,
            "automated_sources": automated_sources,
            "manual_sources": manual_sources,
            "blocked_sources": blocked_sources,
        },
        "forbidden_artifact_usage": forbidden_artifact_usage,
        "r4_7_gate_passed": r4_7_gate_passed,
        "phase_7_8_blocked": True,
        "phase_7_8_block_reason": "R4.7 scaffolding only; Phase 7/8 remains blocked until validated backfill + R5/R6 gates",
        "outputs": {
            "backfill_runner_plan": "data/exports/backfill_runner_plan_r4_7.json",
            "backfill_runner_manifest": "data/exports/backfill_runner_manifest_r4_7.csv",
            "import_slots": "data/exports/import_slots_r4_7.csv",
            "manual_import_slots_required": "data/review_queue/manual_import_slots_required.csv",
            "backfill_runner_blockers": "data/review_queue/backfill_runner_blockers.csv",
        },
    }
    _write_json(exports_dir / "backfill_runner_plan_r4_7.json", plan_payload)

    prior_rebuild = _read_json(exports_dir / "rebuild_status.json")
    rebuild_status = dict(prior_rebuild)
    rebuild_status.update(
        {
            "r4_7_generated_at": plan_payload["generated_at"],
            "row_fabrication_policy": row_fabrication_policy,
            "r4_7_phase_type": phase_type,
            "r4_7_runner_scaffolding_completed": runner_scaffolding_completed,
            "r4_7_data_recovery_completed": data_recovery_completed,
            "r4_7_downloads_executed": downloads_executed,
            "r4_7_rows_ingested": rows_ingested,
            "r4_7_production_inputs_staged": production_inputs_staged,
            "r4_7_automated_source_count_definition": automated_source_count_definition,
            "r4_7_gate_passed": r4_7_gate_passed,
            "r4_7_total_sources": total_sources,
            "r4_7_automated_sources": automated_sources,
            "r4_7_manual_sources": manual_sources,
            "r4_7_blocked_sources": blocked_sources,
            "r4_7_execute_downloads_default": False,
            "phase_7_8_blocked": True,
            "phase_7_8_block_reason": plan_payload["phase_7_8_block_reason"],
            "r4_7_outputs": plan_payload["outputs"],
        }
    )
    _write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return plan_payload
