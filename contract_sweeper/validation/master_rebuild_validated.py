"""R4.9 validated-only master rebuild orchestration."""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from contract_sweeper.validation.master_input_recovery import AWARD_SIGNAL_COLUMNS, expected_builder_inputs
from scripts import build_unified_master


FORBIDDEN_INPUT_TOKENS = (
    "report",
    "summary",
    "top_nodes",
    "network_summary",
    "network.graphml",
    "dominance",
    "power_network",
    "prime_sub",
)


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


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _manifest_exists(path: Path) -> bool:
    candidates = (
        path.with_suffix(path.suffix + ".manifest.json"),
        path.parent / "manifest.json",
        path.parent / "_manifest.json",
    )
    return any(candidate.exists() for candidate in candidates)


def _schema_valid(path: Path) -> bool:
    if not path.exists() or path.suffix.lower() != ".csv":
        return False
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        cols = {str(c).strip().lower() for c in (reader.fieldnames or []) if c}
    return len(cols.intersection(AWARD_SIGNAL_COLUMNS)) >= 2


def _is_forbidden(path: Path, root: Path) -> bool:
    rel = str(path.resolve().relative_to(root.resolve())).lower()
    return any(token in rel for token in FORBIDDEN_INPUT_TOKENS)


def run_r4_9_master_rebuild(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports = root / "data" / "exports"
    review = root / "data" / "review_queue"
    processed = root / "data" / "staging" / "processed"

    inputs = expected_builder_inputs(root)
    blockers: list[dict[str, Any]] = []

    for spec in inputs:
        path = root / spec.expected_relpath
        blocker = {
            "expected_relpath": spec.expected_relpath,
            "dataset_label": spec.dataset_label,
            "input_group": spec.input_group,
            "exists": path.exists(),
            "manifest_exists": _manifest_exists(path),
            "schema_valid": _schema_valid(path),
            "forbidden_artifact": _is_forbidden(path, root) if path.exists() else False,
        }
        if not (blocker["exists"] and blocker["manifest_exists"] and blocker["schema_valid"]) or blocker["forbidden_artifact"]:
            blockers.append(blocker)

    _write_csv(
        exports / "r4_9_rebuild_audit.csv",
        blockers,
        ["expected_relpath", "dataset_label", "input_group", "exists", "manifest_exists", "schema_valid", "forbidden_artifact"],
    )

    prior = _read_json(exports / "rebuild_status.json")
    rebuild_status = dict(prior)

    if blockers:
        rebuild_status.update(
            {
                "r4_9_generated_at": _utc_now(),
                "r4_9_gate_passed": False,
                "r4_9_blocker_count": len(blockers),
                "r4_9_outputs": {"rebuild_audit": "data/exports/r4_9_rebuild_audit.csv"},
                "phase_7_8_blocked": True,
                "phase_7_8_block_reason": "R4.9 gate failed; awaiting manifest-backed schema-valid inputs",
            }
        )
        _write_json(exports / "rebuild_status.json", rebuild_status)
        _write_csv(review / "r4_9_rebuild_blockers.csv", blockers, list(blockers[0].keys()))
        return rebuild_status

    summary = build_unified_master.run(root=root, require_all_inputs=True, fail_on_forbidden=True)
    all_awards_path = processed / "pr_all_awards_master.csv"
    awards_df = pd.read_csv(all_awards_path, dtype=str, low_memory=False)

    contracts = awards_df[awards_df.get("source_dataset", "").astype(str).str.lower() == "contracts"].copy()
    contracts_path = processed / "contracts_master.parquet"
    contracts.to_parquet(contracts_path, index=False)

    contribution = (
        awards_df.groupby(["source_system", "source_dataset"], dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values("rows", ascending=False)
    )
    contribution.to_csv(exports / "r4_9_source_contribution_matrix.csv", index=False)

    dedup = {
        "generated_at": _utc_now(),
        "total_rows": int(len(awards_df)),
        "unique_source_record_ids": int(awards_df.get("source_record_id", pd.Series(dtype=str)).nunique()),
        "duplicate_source_record_ids": int(awards_df.get("source_record_id", pd.Series(dtype=str)).duplicated().sum()),
        "summary": summary,
    }
    _write_json(exports / "r4_9_deduplication_trace.json", dedup)

    rebuild_status.update(
        {
            "r4_9_generated_at": _utc_now(),
            "r4_9_gate_passed": True,
            "r4_9_blocker_count": 0,
            "r4_9_outputs": {
                "rebuild_audit": "data/exports/r4_9_rebuild_audit.csv",
                "source_contribution_matrix": "data/exports/r4_9_source_contribution_matrix.csv",
                "deduplication_trace": "data/exports/r4_9_deduplication_trace.json",
                "pr_all_awards_master": "data/staging/processed/pr_all_awards_master.csv",
                "contracts_master": "data/staging/processed/contracts_master.parquet",
            },
            "r4_9_forbidden_artifact_usage": False,
            "row_fabrication_policy": "FORBIDDEN_NO_SYNTHETIC_ROWS",
            "phase_7_8_blocked": True,
            "phase_7_8_block_reason": "R4.9 completed; keep blocked pending R5 entity resolution",
        }
    )
    _write_json(exports / "rebuild_status.json", rebuild_status)
    return rebuild_status
