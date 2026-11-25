"""Per-source executor (spec §10 executor / §13 / §14).

Runs one source at a time via ``sys.executable`` with an argument array (never
shell interpolation), enforces a timeout, captures bounded output, retries only
retryable statuses, snapshots outputs before/after, and commits materialization
state only after the output gates pass. A failed refresh never deletes or
truncates prior valid output.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from moneysweep.update_controller.drop_scanner import mark_consumed, scan_source
from moneysweep.update_controller.models import (
    CADENCE_INTERVAL_HOURS,
    RETRYABLE_STATUSES,
    SUCCESS_STATUSES,
    ExecutionStatus,
    FailurePacket,
    SourceUpdatePolicy,
    UpdateRunRecord,
)
from moneysweep.update_controller.planner import missing_secrets
from moneysweep.update_controller.state import append_failure, append_run
from moneysweep.update_controller.validation import (
    snapshot_outputs,
    validate_outputs,
    verify_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_CAPTURED_LINES = 40


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _new_run_id() -> str:
    return uuid.uuid4().hex


def _tail(text: str, n: int = MAX_CAPTURED_LINES) -> list[str]:
    lines = (text or "").splitlines()
    return lines[-n:]


def classify_failure(exit_code: int | None, output: str) -> tuple[str, str, bool]:
    """Map a producer failure to (status, suspected_area, retryable)."""
    low = (output or "").lower()
    if "rate limit" in low or "429" in low or "too many requests" in low:
        return ExecutionStatus.RATE_LIMITED.value, "rate_limit", True
    if "timed out" in low or "timeout" in low:
        return ExecutionStatus.PRODUCER_EXECUTION_FAILED.value, "timeout", False
    if any(m in low for m in ("connection", "temporarily unavailable", "503", "502")):
        return ExecutionStatus.SOURCE_UNAVAILABLE.value, "network", True
    if "modulenotfounderror" in low or "importerror" in low:
        return ExecutionStatus.PRODUCER_IMPORT_FAILED.value, "producer_import", False
    return ExecutionStatus.PRODUCER_EXECUTION_FAILED.value, "producer_execution", False


def _preflight_ok(root: Path, registry_entry: dict[str, Any]) -> tuple[bool, str]:
    """Strict per-source preflight (importability/entrypoint) — no execution."""
    try:
        from scripts.pipeline_preflight import (
            STRUCTURAL_STATUSES,
            classify_source_readiness,
        )

        status = classify_source_readiness(root, registry_entry)["readiness_status"]
        return (status not in STRUCTURAL_STATUSES), status
    except Exception as exc:  # noqa: BLE001
        return False, f"preflight_error:{type(exc).__name__}"


def run_source(
    policy: SourceUpdatePolicy,
    registry_entry: dict[str, Any],
    state: dict[str, Any],
    *,
    root: Path | None = None,
    dotenv: dict[str, Any] | None = None,
    now: datetime | None = None,
    consumed_path: str | Path | None = None,
    dry_run: bool = False,
    strict: bool = True,
) -> dict[str, Any]:
    """Execute (or gate) a single source; mutate ``state`` in place; return a result."""
    root = root or REPO_ROOT
    now = now or _now()
    dotenv = dotenv if dotenv is not None else {}
    sid = policy.source_id
    row = state.setdefault("sources", {}).setdefault(sid, {})
    run_id = _new_run_id()
    expected = list(registry_entry.get("expected_outputs") or [])

    def finish(
        status: str,
        exit_code: int | None = None,
        failure: FailurePacket | None = None,
    ) -> dict[str, Any]:
        row["last_attempt_at"] = _iso(now)
        row["last_status"] = status
        row["last_exit_code"] = exit_code
        row["last_run_id"] = run_id
        if status in SUCCESS_STATUSES:
            row["consecutive_failures"] = 0
        elif status not in (
            ExecutionStatus.NOT_DUE.value,
            ExecutionStatus.DISABLED.value,
            ExecutionStatus.MANUAL_INPUT_MISSING.value,
            ExecutionStatus.DEPENDENCY_NOT_READY.value,
            ExecutionStatus.MISSING_SECRET.value,
        ):
            row["consecutive_failures"] = int(row.get("consecutive_failures", 0)) + 1
        return {
            "source_id": sid,
            "run_id": run_id,
            "status": status,
            "exit_code": exit_code,
            "failure_packet": failure.to_dict() if failure else None,
            "government_change_monitor": row.get("government_change_monitor"),
        }

    # -- Non-executing gates first ------------------------------------------
    if policy.trigger_type == "disabled" or not policy.enabled:
        return finish(ExecutionStatus.DISABLED.value)

    miss = missing_secrets(policy, dotenv)
    if miss:
        # Non-fatal, non-structural: report by name only, never the value.
        return finish(ExecutionStatus.MISSING_SECRET.value)

    if policy.trigger_type in ("file_drop", "on_drop"):
        new_drops = [c for c in scan_source(policy, root, consumed_path) if c.is_new]
        if not new_drops:
            return finish(ExecutionStatus.MANUAL_INPUT_MISSING.value)

    if strict:
        ok, pf_status = _preflight_ok(root, registry_entry)
        if not ok:
            packet = FailurePacket(
                command=[sys.executable, policy.runner, *policy.runner_args],
                exit_code=None,
                source_id=sid,
                run_id=run_id,
                status=ExecutionStatus.PRODUCER_IMPORT_FAILED.value,
                suspected_area="preflight",
                retryable=False,
                last_40_lines=[f"preflight: {pf_status}"],
            )
            append_failure(packet.to_dict(), root)
            return finish(ExecutionStatus.PRODUCER_IMPORT_FAILED.value, None, packet)

    command = [sys.executable, policy.runner, *policy.runner_args]
    if dry_run:
        return {
            "source_id": sid,
            "run_id": run_id,
            "status": ExecutionStatus.PLANNED.value,
            "command": command,
            "exit_code": None,
            "failure_packet": None,
        }

    # -- Execute with retries on retryable statuses -------------------------
    before = snapshot_outputs(root, expected)
    started = _now()
    attempt = 0
    status = ExecutionStatus.PRODUCER_EXECUTION_FAILED.value
    exit_code: int | None = None
    captured = ""
    while attempt <= policy.max_retries:
        attempt += 1
        try:
            proc = subprocess.run(
                command,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=policy.timeout_minutes * 60,
                check=False,
            )
            exit_code = proc.returncode
            captured = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except subprocess.TimeoutExpired as exc:
            exit_code = None
            captured = f"TimeoutExpired after {policy.timeout_minutes}m: {exc}"
            status = ExecutionStatus.PRODUCER_EXECUTION_FAILED.value
            break
        except Exception as exc:  # noqa: BLE001
            exit_code = None
            captured = f"{type(exc).__name__}: {exc}"
            status = ExecutionStatus.PRODUCER_EXECUTION_FAILED.value
            break

        if exit_code == 0:
            status = ExecutionStatus.SUCCESS_WITH_CHANGE.value
            break
        status, _area, retryable = classify_failure(exit_code, captured)
        if not (retryable and status in RETRYABLE_STATUSES and attempt <= policy.max_retries):
            break

    finished = _now()
    after = snapshot_outputs(root, expected)

    record = UpdateRunRecord(
        run_id=run_id,
        source_id=sid,
        trigger=policy.trigger_type,
        started_at=_iso(started),
        finished_at=_iso(finished),
        status=status,
        exit_code=exit_code,
        attempt=attempt,
        command=command,
        output_hashes_before={k: v.sha256 for k, v in before.items()},
        output_hashes_after={k: v.sha256 for k, v in after.items()},
        row_counts_before={k: v.row_count for k, v in before.items()},
        row_counts_after={k: v.row_count for k, v in after.items()},
        duration_seconds=round((finished - started).total_seconds(), 2),
    )

    if exit_code != 0 or status not in (ExecutionStatus.SUCCESS_WITH_CHANGE.value,):
        st, area, retryable = classify_failure(exit_code, captured)
        packet = FailurePacket(
            command=command,
            exit_code=exit_code,
            source_id=sid,
            run_id=run_id,
            status=st,
            suspected_area=area,
            retryable=retryable,
            last_40_lines=_tail(captured),
        )
        record.status = st
        record.failure_packet = packet.to_dict()
        append_run(record.to_dict(), root)
        append_failure(packet.to_dict(), root)
        # prior valid output stays authoritative — no state materialization update
        return finish(st, exit_code, packet)

    # -- Zero exit → output gates ------------------------------------------
    gate = validate_outputs(root, policy, registry_entry, before, after)
    atomic_ok = (not policy.atomic_output_required) or verify_atomic(root, expected)
    gate_status = gate["status"]
    passed = gate["passed"] and atomic_ok
    record.status = gate_status
    append_run(record.to_dict(), root)

    if not passed:
        packet = FailurePacket(
            command=command,
            exit_code=exit_code,
            source_id=sid,
            run_id=run_id,
            status=gate_status,
            suspected_area=(
                "output_regression"
                if gate_status == ExecutionStatus.OUTPUT_REGRESSION.value
                else "output_missing"
                if gate_status == ExecutionStatus.OUTPUT_MISSING.value
                else "schema"
            ),
            retryable=False,
            last_40_lines=_tail(captured),
        )
        append_failure(packet.to_dict(), root)
        return finish(gate_status, exit_code, packet)

    # -- Success: commit materialization state -----------------------------
    row["output_hashes"] = {k: v.sha256 for k, v in after.items()}
    row["output_row_counts"] = {k: v.row_count for k, v in after.items()}
    row["output_manifest_hash"] = _combined_hash(after)
    row["last_success_at"] = _iso(finished)
    if gate_status in (
        ExecutionStatus.SUCCESS_WITH_CHANGE.value,
        ExecutionStatus.SUCCESS_NO_CHANGE.value,
        ExecutionStatus.EMPTY_EXPECTED.value,
    ):
        row["last_materialized_at"] = _iso(finished)
    if gate_status == ExecutionStatus.SUCCESS_WITH_CHANGE.value:
        row["last_output_change_at"] = _iso(finished)

    interval = CADENCE_INTERVAL_HOURS.get((policy.cadence or "").lower())
    if policy.trigger_type == "schedule" and interval:
        row["next_due_at"] = _iso(finished + timedelta(hours=interval))

    if policy.trigger_type == "dependency":
        consumed = row.setdefault("dependency_versions_consumed", {})
        for parent in policy.depends_on:
            phash = state.get("sources", {}).get(parent, {}).get("output_manifest_hash")
            if phash:
                consumed[parent] = phash

    if policy.trigger_type in ("file_drop", "on_drop"):
        for cand in scan_source(policy, root, consumed_path):
            if cand.is_new:
                mark_consumed(sid, cand.sha256, root, consumed_path)

    # Government organization-change discovery is a post-validation control
    # plane. It cannot invalidate an otherwise valid source refresh, but any
    # monitor failure is surfaced in source state/result instead of being silent.
    if gate_status == ExecutionStatus.SUCCESS_WITH_CHANGE.value:
        try:
            from moneysweep.government_change_materialization import (
                materialize_validated_source_update,
            )

            row["government_change_monitor"] = materialize_validated_source_update(
                source_id=sid,
                run_id=run_id,
                output_hashes={k: v.sha256 for k, v in after.items()},
                root=root,
            )
        except Exception as exc:  # noqa: BLE001
            row["government_change_monitor"] = {
                "status": "MONITOR_ERROR",
                "error_type": type(exc).__name__,
                "message": str(exc),
            }
    else:
        row["government_change_monitor"] = {
            "status": "NO_OUTPUT_CHANGE",
            "source_id": sid,
        }

    return finish(gate_status, exit_code)


def run_source_isolated(
    policy: SourceUpdatePolicy,
    registry_entry: dict[str, Any],
    state: dict[str, Any],
    **kwargs: Any,
) -> dict[str, Any]:
    """``run_source`` that turns a controller-side crash into a failed result.

    ``run_source`` already contains producer failures, but an exception raised
    by the controller itself (snapshotting an output, scanning a dropzone)
    used to escape the worker and abort every other source in the cadence.
    Record it against this source only; the batch still exits non-zero.
    """
    try:
        return run_source(policy, registry_entry, state, **kwargs)
    except Exception as exc:  # noqa: BLE001 - one source must not abort the cadence
        sid = policy.source_id
        run_id = _new_run_id()
        status = ExecutionStatus.PRODUCER_EXECUTION_FAILED.value
        packet = FailurePacket(
            command=[sys.executable, policy.runner, *policy.runner_args],
            exit_code=None,
            source_id=sid,
            run_id=run_id,
            status=status,
            suspected_area="update_controller",
            retryable=False,
            last_40_lines=[f"{type(exc).__name__}: {exc}"[:500]],
        )
        if not kwargs.get("dry_run"):
            append_failure(packet.to_dict(), kwargs.get("root"))
        row = state.setdefault("sources", {}).setdefault(sid, {})
        row["last_attempt_at"] = _iso(kwargs.get("now") or _now())
        row["last_status"] = status
        row["last_exit_code"] = None
        row["last_run_id"] = run_id
        row["consecutive_failures"] = int(row.get("consecutive_failures", 0)) + 1
        return {
            "source_id": sid,
            "run_id": run_id,
            "status": status,
            "exit_code": None,
            "failure_packet": packet.to_dict(),
            "government_change_monitor": row.get("government_change_monitor"),
        }


def _combined_hash(snapshots: dict[str, Any]) -> str:
    import hashlib

    parts = [f"{k}:{snapshots[k].sha256 or ''}" for k in sorted(snapshots)]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
