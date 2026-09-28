"""Output validation, atomicity checks and freshness computation (spec §12/§13).

Reuses the registry's per-source ``validation_threshold`` (``min_rows`` etc.).
Never deletes or truncates prior valid output — a failed refresh leaves the
previous output authoritative.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from moneysweep.update_controller.models import (
    CADENCE_SLA_HOURS,
    ExecutionStatus,
    FreshnessResult,
    FreshnessStatus,
    OutputSnapshot,
    SourceUpdatePolicy,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def count_rows(path: Path) -> int | None:
    """Row count for CSV (excludes header) / JSONL (line count). None otherwise."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            n = sum(1 for line in f if line.strip() != "")
        return max(0, n - 1)  # minus header
    if suffix in (".jsonl", ".ndjson"):
        with path.open("r", encoding="utf-8", errors="replace") as f:
            return sum(1 for line in f if line.strip() != "")
    return None


def snapshot_output(root: Path, rel: str) -> OutputSnapshot:
    p = root / rel
    if not p.exists():
        return OutputSnapshot(path=rel, exists=False)

    if p.is_dir():
        # A few source contracts intentionally declare a raw-evidence directory
        # alongside a processed file. Snapshot directories deterministically
        # instead of trying to open them as files. Symlinks are represented by
        # their link target text and are never followed outside the declared tree.
        h = hashlib.sha256()
        size_bytes = 0
        mtimes: list[float] = [p.stat().st_mtime]
        for child in sorted(p.rglob("*"), key=lambda item: item.relative_to(p).as_posix()):
            relative = child.relative_to(p).as_posix()
            if child.is_symlink():
                target = child.readlink().as_posix()
                h.update(f"L\\0{relative}\\0{target}\\n".encode("utf-8"))
                mtimes.append(child.lstat().st_mtime)
                continue
            if not child.is_file():
                continue
            st = child.stat()
            digest = sha256_file(child)
            h.update(f"F\\0{relative}\\0{st.st_size}\\0{digest}\\n".encode("utf-8"))
            size_bytes += st.st_size
            mtimes.append(st.st_mtime)
        return OutputSnapshot(
            path=rel,
            exists=True,
            size_bytes=size_bytes,
            sha256=h.hexdigest(),
            row_count=None,
            mtime=max(mtimes),
        )

    st = p.stat()
    return OutputSnapshot(
        path=rel,
        exists=True,
        size_bytes=st.st_size,
        sha256=sha256_file(p),
        row_count=count_rows(p),
        mtime=st.st_mtime,
    )


def snapshot_outputs(root: Path, expected_outputs: list[str]) -> dict[str, OutputSnapshot]:
    return {rel: snapshot_output(root, rel) for rel in expected_outputs}


def _within_root(root: Path, rel: str) -> bool:
    try:
        (root / rel).resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _header_only(root: Path, rel: str) -> bool:
    p = root / rel
    if p.suffix.lower() != ".csv" or not p.exists():
        return False
    rows = count_rows(p)
    with p.open("r", encoding="utf-8", errors="replace") as f:
        first = f.readline().strip()
    return bool(first) and (rows == 0)


def _parses(root: Path, rel: str) -> bool:
    p = root / rel
    suffix = p.suffix.lower()
    try:
        if suffix == ".json":
            json.loads(p.read_text(encoding="utf-8"))
        elif suffix in (".jsonl", ".ndjson"):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    json.loads(line)
    except Exception:
        return False
    return True


def validate_outputs(
    root: Path,
    policy: SourceUpdatePolicy,
    registry_entry: dict[str, Any],
    before: dict[str, OutputSnapshot],
    after: dict[str, OutputSnapshot],
) -> dict[str, Any]:
    """Post-run output gates (spec §13). Returns {status, passed, checks[]}.

    A failed gate never mutates or deletes output — the caller keeps the prior
    valid output authoritative.
    """
    expected = list(registry_entry.get("expected_outputs") or [])
    threshold = registry_entry.get("validation_threshold") or {}
    min_rows = policy.minimum_output_rows
    if min_rows is None:
        min_rows = int(threshold.get("min_rows", 1))
    checks: list[dict[str, Any]] = []
    status = ExecutionStatus.SUCCESS_WITH_CHANGE.value

    def add(name: str, ok: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": ok, "detail": detail})

    # 8. no output outside repo root
    for rel in expected:
        add("within_repo_root", _within_root(root, rel), rel)
    if any(not c["passed"] for c in checks if c["check"] == "within_repo_root"):
        return {"status": ExecutionStatus.SCHEMA_FAILED.value, "passed": False, "checks": checks}

    # 1. all required expected outputs exist
    missing = [rel for rel in expected if not (root / rel).exists()]
    for rel in expected:
        add("output_exists", (root / rel).exists(), rel)
    if missing:
        return {"status": ExecutionStatus.OUTPUT_MISSING.value, "passed": False, "checks": checks}

    # total post-run rows across CSV/JSONL outputs
    total_after = 0
    counted = False
    for rel in expected:
        rc = after[rel].row_count if rel in after else count_rows(root / rel)
        if rc is not None:
            total_after += rc
            counted = True

    # 6/7. JSON/JSONL parse
    for rel in expected:
        if (root / rel).suffix.lower() in (".json", ".jsonl", ".ndjson"):
            ok = _parses(root, rel)
            add("parses", ok, rel)
            if not ok:
                return {
                    "status": ExecutionStatus.SCHEMA_FAILED.value,
                    "passed": False,
                    "checks": checks,
                }

    # 5. zero-row (all outputs empty) follows empty_result_policy — evaluated
    # before the header-only check so a legitimately-empty result can be
    # preserved rather than hard-failing (spec §13.5).
    if counted and total_after == 0:
        pol = policy.empty_result_policy
        add("empty_result_policy", True, f"{pol}; rows=0")
        if pol == "fail":
            return {
                "status": ExecutionStatus.EMPTY_SUSPICIOUS.value,
                "passed": False,
                "checks": checks,
            }
        # preserve_previous / warn / allow → suspicious-empty (does not refresh
        # materialization freshness, spec §12.9); previous output stays.
        return {
            "status": ExecutionStatus.EMPTY_SUSPICIOUS.value
            if pol == "preserve_previous"
            else ExecutionStatus.EMPTY_EXPECTED.value,
            "passed": pol in ("allow", "warn", "preserve_previous"),
            "checks": checks,
        }

    # 3. header-only output fails when other outputs carry data (partial write)
    header_only = [rel for rel in expected if _header_only(root, rel)]
    for rel in header_only:
        add("not_header_only", False, rel)
    if header_only:
        return {"status": ExecutionStatus.SCHEMA_FAILED.value, "passed": False, "checks": checks}

    # 2. min_rows from registry
    if counted:
        ok = total_after >= min_rows
        add("min_rows", ok, f"rows={total_after} >= {min_rows}")
        if not ok:
            return {
                "status": ExecutionStatus.SCHEMA_FAILED.value,
                "passed": False,
                "checks": checks,
            }

    # 4. row regression beyond tolerance fails
    total_before = 0
    had_before = False
    for rel in expected:
        rc = before[rel].row_count if rel in before else None
        if rc is not None:
            total_before += rc
            had_before = True
    changed = True
    if had_before and total_before > 0:
        drop_pct = max(0.0, (total_before - total_after) / total_before * 100.0)
        tol = policy.row_regression_tolerance_pct
        ok = drop_pct <= tol
        add("row_regression", ok, f"drop={drop_pct:.1f}% <= {tol}%")
        if not ok:
            return {
                "status": ExecutionStatus.OUTPUT_REGRESSION.value,
                "passed": False,
                "checks": checks,
            }
        # unchanged output → SUCCESS_NO_CHANGE
        hashes_before = {rel: before[rel].sha256 for rel in expected if rel in before}
        hashes_after = {rel: after[rel].sha256 for rel in expected if rel in after}
        changed = hashes_before != hashes_after

    status = (
        ExecutionStatus.SUCCESS_WITH_CHANGE.value
        if changed
        else ExecutionStatus.SUCCESS_NO_CHANGE.value
    )
    return {"status": status, "passed": True, "checks": checks, "rows": total_after}


def verify_atomic(root: Path, expected_outputs: list[str]) -> bool:
    """True if no partial ``.tmp`` shadow file is left beside any output."""
    for rel in expected_outputs:
        if (root / (rel + ".tmp")).exists():
            return False
    return True


# --------------------------------------------------------------------------- #
# Freshness (spec §12)
# --------------------------------------------------------------------------- #
def _age_hours(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        dt = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    return (now - dt).total_seconds() / 3600.0


def compute_freshness(
    policy: SourceUpdatePolicy,
    state_row: dict[str, Any],
    update_cadence: str,
    has_output: bool,
    now: datetime | None = None,
) -> FreshnessResult:
    now = now or datetime.now(timezone.utc)
    last_success = state_row.get("last_success_at")
    last_mat = state_row.get("last_materialized_at")
    age = _age_hours(last_mat, now)
    sla = policy.freshness_sla_hours
    grace = policy.freshness_grace_hours

    if policy.terminal:
        status = FreshnessStatus.TERMINAL.value
    elif policy.path_type in ("deferred_stub", "scraper_needed"):
        status = FreshnessStatus.DISABLED.value
    elif policy.trigger_type == "disabled" or not policy.enabled:
        status = FreshnessStatus.DISABLED.value
    elif policy.trigger_type in ("file_drop",) and policy.required and not has_output:
        status = FreshnessStatus.BLOCKED_MANUAL_INPUT.value
    elif last_mat is None:
        status = FreshnessStatus.NEVER_MATERIALIZED.value
    elif sla <= 0:
        # ad_hoc / no time-based SLA — materialized ⇒ fresh
        status = FreshnessStatus.FRESH.value
    elif age is None:
        status = FreshnessStatus.UNKNOWN.value
    elif age <= sla:
        status = FreshnessStatus.FRESH.value
    elif age <= sla + grace:
        status = FreshnessStatus.DUE.value
    else:
        status = FreshnessStatus.STALE.value

    return FreshnessResult(
        source_id=policy.source_id,
        trigger_type=policy.trigger_type,
        enabled=policy.enabled,
        required=policy.required,
        path_type=policy.path_type,
        update_cadence=update_cadence,
        freshness_sla_hours=sla,
        last_success_at=last_success,
        last_materialized_at=last_mat,
        age_hours=age,
        freshness_status=status,
        next_due_at=state_row.get("next_due_at"),
        consecutive_failures=int(state_row.get("consecutive_failures", 0) or 0),
        last_status=str(state_row.get("last_status", ExecutionStatus.NEVER_RUN.value)),
    )


def freshness_exit_code(results: list[FreshnessResult]) -> int:
    """0 = all enabled required fresh; 1 = optional stale/warnings; 2 = required stale/failed.

    Per spec §12.2 a BLOCKED_MANUAL_INPUT required source escalates to exit 2 only
    once its SLA has expired (it has a materialization baseline older than the
    SLA); a never-materialized source is a bootstrap *warning* (exit 1), not a
    hard failure.
    """
    required_fail = False
    warn = False
    for r in results:
        st = r.freshness_status
        if st == FreshnessStatus.STALE.value and r.required and r.enabled:
            required_fail = True
        elif st == FreshnessStatus.BLOCKED_MANUAL_INPUT.value and r.required:
            if r.age_hours is not None and r.age_hours > r.freshness_sla_hours:
                required_fail = True
            else:
                warn = True
        elif st in (
            FreshnessStatus.STALE.value,
            FreshnessStatus.DUE.value,
            FreshnessStatus.BLOCKED_MANUAL_INPUT.value,
            FreshnessStatus.NEVER_MATERIALIZED.value,
        ):
            warn = True
    if required_fail:
        return 2
    return 1 if warn else 0


def cadence_sla_hours(cadence: str) -> float | None:
    return CADENCE_SLA_HOURS.get(cadence)
