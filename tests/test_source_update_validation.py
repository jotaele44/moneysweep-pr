"""Output-validation + freshness tests for the source update controller."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from moneysweep.update_controller.models import SourceUpdatePolicy
from moneysweep.update_controller.validation import (
    compute_freshness,
    snapshot_outputs,
    validate_outputs,
)

pytestmark = pytest.mark.unit


def _pol(empty_policy="preserve_previous", tol=40.0) -> SourceUpdatePolicy:
    return SourceUpdatePolicy(
        source_id="x",
        trigger_type="schedule",
        enabled=True,
        runner="scripts/x.py",
        freshness_sla_hours=192,
        timeout_minutes=60,
        max_retries=0,
        empty_result_policy=empty_policy,
        row_regression_tolerance_pct=tol,
        cadence="weekly",
    )


def _entry(min_rows=1):
    return {
        "source_id": "x",
        "expected_outputs": ["data/out.csv"],
        "validation_threshold": {"min_rows": min_rows},
    }


def _write(root, rows: int):
    p = root / "data"
    p.mkdir(exist_ok=True)
    body = "a,b\n" + "".join(f"{i},{i}\n" for i in range(rows))
    (p / "out.csv").write_text(body)


def test_directory_output_snapshot_is_deterministic_and_does_not_follow_symlinks(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "a.txt").write_text("alpha", encoding="utf-8")
    nested = raw / "nested"
    nested.mkdir()
    (nested / "b.txt").write_text("beta", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside-v1", encoding="utf-8")
    (raw / "outside-link").symlink_to(outside)

    first = snapshot_outputs(tmp_path, ["data/raw"])["data/raw"]
    outside.write_text("outside-v2", encoding="utf-8")
    second = snapshot_outputs(tmp_path, ["data/raw"])["data/raw"]

    assert first.exists is True
    assert first.row_count is None
    assert first.size_bytes == len("alpha") + len("beta")
    assert first.sha256 == second.sha256


def test_directory_and_csv_outputs_validate_together(tmp_path):
    raw = tmp_path / "data" / "raw"
    raw.mkdir(parents=True)
    (raw / "evidence.pdf").write_bytes(b"%PDF-frozen-evidence")
    _write(tmp_path, 3)
    expected = ["data/raw", "data/out.csv"]
    before = snapshot_outputs(tmp_path, expected)
    after = snapshot_outputs(tmp_path, expected)
    entry = _entry(min_rows=1)
    entry["expected_outputs"] = expected
    res = validate_outputs(tmp_path, _pol(), entry, before, after)
    assert res["passed"] is True
    assert res["status"] == "SUCCESS_NO_CHANGE"


def test_missing_output_fails(tmp_path):
    (tmp_path / "data").mkdir()
    before = snapshot_outputs(tmp_path, ["data/out.csv"])
    after = snapshot_outputs(tmp_path, ["data/out.csv"])
    res = validate_outputs(tmp_path, _pol(), _entry(), before, after)
    assert res["status"] == "OUTPUT_MISSING"
    assert res["passed"] is False


def test_min_rows_enforced(tmp_path):
    before = snapshot_outputs(tmp_path, ["data/out.csv"])
    _write(tmp_path, 2)
    after = snapshot_outputs(tmp_path, ["data/out.csv"])
    res = validate_outputs(tmp_path, _pol(), _entry(min_rows=10), before, after)
    assert res["status"] == "SCHEMA_FAILED"
    assert res["passed"] is False


def test_header_only_fails(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "out.csv").write_text("a,b\n")  # header, no rows
    before = {}
    after = snapshot_outputs(tmp_path, ["data/out.csv"])
    res = validate_outputs(tmp_path, _pol(), _entry(min_rows=1), before, after)
    assert res["status"] in ("SCHEMA_FAILED", "EMPTY_SUSPICIOUS")
    assert res["passed"] is False or res["status"] == "EMPTY_SUSPICIOUS"


def test_suspicious_zero_rows_preserves_previous(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "out.csv").write_text("a,b\n")  # zero data rows
    before = snapshot_outputs(tmp_path, ["data/out.csv"])
    after = snapshot_outputs(tmp_path, ["data/out.csv"])
    res = validate_outputs(tmp_path, _pol("preserve_previous"), _entry(), before, after)
    assert res["status"] == "EMPTY_SUSPICIOUS"


def test_large_row_regression_fails(tmp_path):
    _write(tmp_path, 100)
    before = snapshot_outputs(tmp_path, ["data/out.csv"])
    _write(tmp_path, 10)  # 90% drop > 40% tolerance
    after = snapshot_outputs(tmp_path, ["data/out.csv"])
    res = validate_outputs(tmp_path, _pol(tol=40.0), _entry(), before, after)
    assert res["status"] == "OUTPUT_REGRESSION"
    assert res["passed"] is False


def test_unchanged_output_returns_success_no_change(tmp_path):
    _write(tmp_path, 5)
    before = snapshot_outputs(tmp_path, ["data/out.csv"])
    after = snapshot_outputs(tmp_path, ["data/out.csv"])  # identical
    res = validate_outputs(tmp_path, _pol(), _entry(), before, after)
    assert res["status"] == "SUCCESS_NO_CHANGE"
    assert res["passed"] is True


def test_valid_changed_output_returns_success_with_change(tmp_path):
    _write(tmp_path, 5)
    before = snapshot_outputs(tmp_path, ["data/out.csv"])
    _write(tmp_path, 6)  # small growth, within tolerance
    after = snapshot_outputs(tmp_path, ["data/out.csv"])
    res = validate_outputs(tmp_path, _pol(), _entry(), before, after)
    assert res["status"] == "SUCCESS_WITH_CHANGE"
    assert res["passed"] is True


# --- freshness ---
def _fresh_pol(
    sla=192, terminal=False, path_type="api_producer", trigger="schedule", required=True
):
    return SourceUpdatePolicy(
        source_id="x",
        trigger_type=trigger,
        enabled=True,
        runner="scripts/x.py",
        freshness_sla_hours=sla,
        timeout_minutes=60,
        max_retries=0,
        empty_result_policy="preserve_previous",
        cadence="weekly",
        path_type=path_type,
        required=required,
        terminal=terminal,
    )


def test_freshness_fresh_stale_never():
    now = datetime(2026, 1, 30, tzinfo=timezone.utc)
    recent = (now - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%SZ")
    old = (now - timedelta(hours=1000)).strftime("%Y-%m-%dT%H:%M:%SZ")

    fr = compute_freshness(_fresh_pol(), {"last_materialized_at": recent}, "weekly", True, now)
    assert fr.freshness_status == "FRESH"

    st = compute_freshness(_fresh_pol(), {"last_materialized_at": old}, "weekly", True, now)
    assert st.freshness_status == "STALE"

    nv = compute_freshness(_fresh_pol(), {"last_materialized_at": None}, "weekly", False, now)
    assert nv.freshness_status == "NEVER_MATERIALIZED"


def test_freshness_terminal_and_disabled():
    now = datetime(2026, 1, 30, tzinfo=timezone.utc)
    term = compute_freshness(
        _fresh_pol(terminal=True, path_type="semantic_duplicate"),
        {"last_materialized_at": None},
        "quarterly",
        False,
        now,
    )
    assert term.freshness_status == "TERMINAL"
