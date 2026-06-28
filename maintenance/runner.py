"""Audit-first maintenance orchestration for moneysweep-pr (top-level package).

collect state -> generic detectors -> repo adapter checks -> report.
Auto-correction only runs in explicit ``safe-correct`` mode.
"""

from __future__ import annotations

from pathlib import Path

from . import corrections, detect
from . import state as state_mod
from .adapters import local
from .models import MaintenanceReport
from .quarantine import write_review_queue
from .report import write_latest_report

REPO_ROOT = Path(__file__).resolve().parent.parent
PROGRAM_ID = "moneysweep-pr"
VALID_MODES = ("audit", "safe-correct")


def run_maintenance(
    root: str | Path | None = None,
    mode: str = "audit",
    write: bool = True,
) -> MaintenanceReport:
    if mode not in VALID_MODES:
        raise ValueError(f"unknown mode {mode!r}; expected one of {VALID_MODES}")
    root_path = Path(root) if root is not None else REPO_ROOT
    state = state_mod.collect_repo_state(root_path)
    repo = state["federation"].get("program_id") or PROGRAM_ID

    findings = []
    findings += detect.detect_missing_required_files(repo, root_path, state)
    findings += detect.detect_invalid_json(repo, root_path, state)
    findings += detect.detect_exact_duplicate_jsonl(repo, root_path, state)
    findings += local.run_checks(repo, root_path, state)

    if mode == "safe-correct":
        for finding in corrections.plan_safe_corrections(findings):
            if not finding.path:
                continue
            removed = corrections.remove_exact_duplicate_jsonl_rows(root_path / finding.path)
            if removed:
                finding.action = "auto_corrected"
                finding.detail = {**(finding.detail or {}), "rows_removed": removed}

    report = MaintenanceReport(repo=repo, findings=findings, mode=mode)
    if write:
        write_latest_report(report, root_path)
        write_review_queue(repo, findings, root_path)
    return report
