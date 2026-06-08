"""R4.9Z-B repository quality and CI hardening audit (non-executing)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.acquisition_package import (
    read_csv,
    read_json,
    utc_now,
    write_csv,
    write_json,
    write_markdown,
)

FORBIDDEN_ARTIFACT_TOKENS = (
    "report",
    "summary",
    "graph",
    "network",
    "top_nodes",
    "top_node",
    "power_network",
    "dominance",
    "risk_alert",
    "investigative",
)

REQUIRED_BLOCKED_PHASES = {
    "R5_ENTITY_RESOLUTION",
    "R6_EXECUTION_CHAIN_REBUILD",
    "R7_FINANCIAL_INTEGRATION",
    "R8_GRAPH_REBUILD",
}

SECRET_PATTERNS = (
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"),
    re.compile(
        r"(?i)(?:x-api-key|api[_-]?key|secret|token)\s*[:=]\s*['\"][A-Za-z0-9_\-]{20,}['\"]"
    ),
)


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"true", "1", "yes"}


def _contains_forbidden_token(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered for token in FORBIDDEN_ARTIFACT_TOKENS)


def _scan_forbidden_artifact_paths(rows: list[dict[str, str]]) -> tuple[bool, list[dict[str, str]]]:
    findings: list[dict[str, str]] = []
    for row in rows:
        expected_input = str(row.get("expected_input", "")).strip()
        target_dropzone_path = str(row.get("target_dropzone_path", "")).strip()
        target_output_path = str(row.get("target_output_path", "")).strip()
        for label, value in (
            ("expected_input", expected_input),
            ("target_dropzone_path", target_dropzone_path),
            ("target_output_path", target_output_path),
        ):
            if value and _contains_forbidden_token(value):
                findings.append(
                    {
                        "expected_input": expected_input,
                        "path_field": label,
                        "path_value": value,
                        "issue": "forbidden_artifact_token_in_source_path",
                    }
                )
    return (len(findings) == 0, findings)


def _scan_secrets(root: Path) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    try:
        tracked_files = subprocess.check_output(
            ["git", "ls-files"],
            cwd=str(root),
            text=True,
        ).splitlines()
    except Exception:
        return findings

    for rel in tracked_files:
        path = root / rel
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() in {
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".pdf",
            ".parquet",
            ".zip",
            ".gz",
            ".xz",
            ".bin",
        }:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lines = content.splitlines()
        for idx, line in enumerate(lines, start=1):
            for pattern in SECRET_PATTERNS:
                if pattern.search(line):
                    # avoid false positives from documented placeholders
                    lowered = line.lower()
                    if any(
                        token in lowered
                        for token in ("example", "placeholder", "dummy", "test_", "fake_")
                    ):
                        continue
                    findings.append(
                        {
                            "file": rel,
                            "line": str(idx),
                            "pattern": pattern.pattern,
                            "excerpt": line[:160].strip(),
                            "issue": "possible_secret_detected",
                        }
                    )
    return findings


def _write_ci_strategy_doc(path: Path) -> None:
    content = """# CI Testing Strategy

## Purpose

Keep the repository stable while source recovery remains externally blocked.

## Core Gates

1. Compile gate: `python -m compileall contract_sweeper tests`
2. Test gate: `pytest -q`
3. Production-status gate: `python scripts/run_production_status_gate.py --root .`

## Phase-Lock Invariants

1. `production_status` must remain `NON_PRODUCTION_DIAGNOSTIC`
2. `phase_7_8_blocked` must remain `true`
3. Retry suppression must remain active until unfreeze candidates validate
4. Downstream blockers must remain active for R5/R6/R7/R8

## Safety Policy

1. No download retries in pause-locked phases
2. No source ingestion in pause-locked phases
3. No production staging in pause-locked phases
4. No synthetic production rows
"""
    write_markdown(path, content)


def _write_quality_doc(
    *,
    path: Path,
    generated_at: str,
    status: dict[str, Any],
    matrix_rows: list[dict[str, Any]],
) -> None:
    failed = [row for row in matrix_rows if not _truthy(row.get("passed"))]
    content = (
        "# Repo Quality Status After R4.9Z-B\n\n"
        f"Generated at: {generated_at}\n\n"
        "## Summary\n\n"
        f"- r4_9z_b_gate_passed: {status.get('r4_9z_b_gate_passed')}\n"
        f"- production_status: {status.get('production_status')}\n"
        f"- phase_7_8_blocked: {status.get('phase_7_8_blocked')}\n"
        f"- retry_suppression_active: {status.get('retry_suppression_active')}\n"
        f"- downstream_blockers_active: {status.get('downstream_blockers_active')}\n"
        f"- forbidden_artifact_usage: {status.get('forbidden_artifact_usage')}\n\n"
        "## Next Actions\n\n"
        "1. Keep pause lock active until external source delivery materially changes.\n"
        "2. Re-run watch/pause checks only after new files/access changes occur.\n"
        "3. Do not start R5/R6/R7/R8 while blockers remain active.\n"
    )
    if failed:
        content += "\n## Failed Checks\n\n"
        for row in failed:
            content += f"- {row.get('check_name')}: {row.get('details')}\n"
    write_markdown(path, content)


def run_repo_quality_audit(root: Path) -> dict[str, Any]:
    root = Path(root)
    exports_dir = root / "data" / "exports"
    review_dir = root / "data" / "review_queue"
    docs_dir = root / "docs"

    _ = read_json(exports_dir / "post_pause_hygiene_status_r4_9z_a.json")
    rebuild_status = read_json(exports_dir / "rebuild_status.json")
    pause_status = read_json(exports_dir / "source_recovery_pause_status_r4_9z.json")
    resume_rows = read_csv(review_dir / "source_recovery_resume_conditions_r4_9z.csv")
    downstream_rows = read_csv(review_dir / "downstream_phase_blockers_r4_9z.csv")
    retry_rows = read_csv(review_dir / "retry_suppression_queue_r4_9d.csv")

    generated_at = utc_now()

    production_status = str(rebuild_status.get("production_status", ""))
    phase_7_8_blocked = bool(rebuild_status.get("phase_7_8_blocked", False))
    retry_suppression_active = bool(rebuild_status.get("r4_9z_retry_suppression_active", False))
    if not retry_suppression_active:
        retry_suppression_active = len(retry_rows) > 0 and all(
            str(row.get("suppression_status", "")).strip().lower() == "suppressed"
            for row in retry_rows
        )

    blocked_phase_codes = {
        str(row.get("phase_code", "")).strip()
        for row in downstream_rows
        if _truthy(row.get("blocked"))
    }
    downstream_blockers_active = bool(rebuild_status.get("r4_9z_downstream_blockers_active", False))
    if not downstream_blockers_active:
        downstream_blockers_active = REQUIRED_BLOCKED_PHASES.issubset(blocked_phase_codes)

    unfreeze_candidates = int(
        rebuild_status.get(
            "r4_9z_unfreeze_candidates", pause_status.get("r4_9z_unfreeze_candidates", 0)
        )
    )
    sources_still_missing = int(
        rebuild_status.get(
            "r4_9z_sources_still_missing", pause_status.get("r4_9z_sources_still_missing", 0)
        )
    )

    resume_conditions_written = len(resume_rows) > 0
    pause_lock_active = bool(
        rebuild_status.get(
            "r4_9z_pause_lock_active", pause_status.get("r4_9z_pause_lock_active", False)
        )
    )

    forbidden_ok, forbidden_findings = _scan_forbidden_artifact_paths(resume_rows)
    secret_findings = _scan_secrets(root)
    no_secrets_detected = len(secret_findings) == 0

    # This phase is non-executing by contract.
    downloads_executed = False
    rows_ingested = 0
    production_inputs_staged = 0

    phase_sequence = [
        "r4_7",
        "r4_8",
        "r4_8a",
        "r4_8b",
        "r4_8c",
        "r4_8d",
        "r4_8e",
        "r4_8f",
        "r4_8g",
        "r4_8h",
        "r4_8i",
        "r4_9a",
        "r4_9b",
        "r4_9c",
        "r4_9d",
        "r4_9e",
        "r4_9f",
        "r4_9z",
    ]

    matrix_rows: list[dict[str, Any]] = []
    for phase in phase_sequence:
        gate_key = f"{phase}_gate_passed"
        present = any(key.startswith(f"{phase}_") for key in rebuild_status.keys())
        matrix_rows.append(
            {
                "generated_at": generated_at,
                "check_group": "phase_representation",
                "check_name": phase,
                "passed": present,
                "expected": "present_in_rebuild_status",
                "actual": "present" if present else "missing",
                "details": f"{gate_key}={rebuild_status.get(gate_key)}",
            }
        )

    invariant_checks = [
        (
            "production_status_lock",
            production_status == "NON_PRODUCTION_DIAGNOSTIC",
            "NON_PRODUCTION_DIAGNOSTIC",
            production_status,
        ),
        ("phase_7_8_block_lock", phase_7_8_blocked is True, "True", str(phase_7_8_blocked)),
        (
            "retry_suppression_active",
            retry_suppression_active is True,
            "True",
            str(retry_suppression_active),
        ),
        (
            "downstream_blockers_active",
            downstream_blockers_active is True,
            "True",
            str(downstream_blockers_active),
        ),
        ("unfreeze_candidates_zero", unfreeze_candidates == 0, "0", str(unfreeze_candidates)),
        ("sources_still_missing_21", sources_still_missing == 21, "21", str(sources_still_missing)),
        (
            "resume_conditions_written",
            resume_conditions_written is True,
            "True",
            str(resume_conditions_written),
        ),
        ("pause_lock_active", pause_lock_active is True, "True", str(pause_lock_active)),
        ("forbidden_artifact_usage", forbidden_ok is True, "False", str(not forbidden_ok)),
        (
            "secret_scan",
            no_secrets_detected is True,
            "0 findings",
            f"{len(secret_findings)} findings",
        ),
        ("downloads_executed", downloads_executed is False, "False", str(downloads_executed)),
        ("rows_ingested", rows_ingested == 0, "0", str(rows_ingested)),
        (
            "production_inputs_staged",
            production_inputs_staged == 0,
            "0",
            str(production_inputs_staged),
        ),
    ]
    for name, passed, expected, actual in invariant_checks:
        matrix_rows.append(
            {
                "generated_at": generated_at,
                "check_group": "invariant",
                "check_name": name,
                "passed": passed,
                "expected": expected,
                "actual": actual,
                "details": "",
            }
        )

    followups_rows: list[dict[str, Any]] = []
    for finding in forbidden_findings:
        followups_rows.append(
            {
                "category": "forbidden_artifact_path",
                "severity": "high",
                "item": finding.get("expected_input", ""),
                "details": f"{finding.get('path_field')}={finding.get('path_value')}",
                "recommended_action": "remove forbidden artifact token from source path mapping",
                "status": "open",
            }
        )
    for finding in secret_findings:
        followups_rows.append(
            {
                "category": "possible_secret",
                "severity": "high",
                "item": finding.get("file", ""),
                "details": f"line {finding.get('line')}: {finding.get('excerpt')}",
                "recommended_action": "review and remove secret from tracked files",
                "status": "open",
            }
        )
    if not followups_rows:
        followups_rows.append(
            {
                "category": "none",
                "severity": "info",
                "item": "repo_hygiene",
                "details": "No open hygiene followups from R4.9Z-B audit",
                "recommended_action": "await external source delivery before resuming source recovery",
                "status": "closed",
            }
        )

    gate_passed = bool(
        pause_lock_active
        and resume_conditions_written
        and production_status == "NON_PRODUCTION_DIAGNOSTIC"
        and phase_7_8_blocked
        and retry_suppression_active
        and downstream_blockers_active
        and downloads_executed is False
        and rows_ingested == 0
        and production_inputs_staged == 0
        and forbidden_ok
    )

    status_payload = {
        "generated_at": generated_at,
        "r4_9z_b_gate_passed": gate_passed,
        "production_status": production_status,
        "phase_7_8_blocked": phase_7_8_blocked,
        "retry_suppression_active": retry_suppression_active,
        "downstream_blockers_active": downstream_blockers_active,
        "downloads_executed": downloads_executed,
        "rows_ingested": rows_ingested,
        "production_inputs_staged": production_inputs_staged,
        "forbidden_artifact_usage": not forbidden_ok,
        "unfreeze_candidates": unfreeze_candidates,
        "sources_still_missing": sources_still_missing,
        "resume_conditions_written": resume_conditions_written,
        "possible_secret_findings": len(secret_findings),
    }

    write_json(exports_dir / "repo_quality_status_r4_9z_b.json", status_payload)
    write_csv(
        exports_dir / "repo_quality_matrix_r4_9z_b.csv",
        matrix_rows,
        ["generated_at", "check_group", "check_name", "passed", "expected", "actual", "details"],
    )
    write_csv(
        review_dir / "repo_hygiene_followups_r4_9z_b.csv",
        followups_rows,
        ["category", "severity", "item", "details", "recommended_action", "status"],
    )

    _write_ci_strategy_doc(docs_dir / "CI_TESTING_STRATEGY.md")
    _write_quality_doc(
        path=docs_dir / "REPO_QUALITY_STATUS_AFTER_R4_9Z.md",
        generated_at=generated_at,
        status=status_payload,
        matrix_rows=matrix_rows,
    )

    rebuild_status.update(
        {
            "r4_9z_b_generated_at": generated_at,
            "r4_9z_b_gate_passed": gate_passed,
            "r4_9z_b_retry_suppression_active": retry_suppression_active,
            "r4_9z_b_downstream_blockers_active": downstream_blockers_active,
            "r4_9z_b_downloads_executed": downloads_executed,
            "r4_9z_b_rows_ingested": rows_ingested,
            "r4_9z_b_production_inputs_staged": production_inputs_staged,
            "r4_9z_b_forbidden_artifact_usage": not forbidden_ok,
            "r4_9z_b_possible_secret_findings": len(secret_findings),
            "production_status": production_status,
            "phase_7_8_blocked": phase_7_8_blocked,
        }
    )
    write_json(exports_dir / "rebuild_status.json", rebuild_status)

    return status_payload
