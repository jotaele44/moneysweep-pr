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


def test_directory_output_snapshot_is_sorted_byte_bound_and_row_conserving(tmp_path):
    rel = "data/raw/HigherGov"
    directory = tmp_path / rel
    directory.mkdir(parents=True)
    (directory / "b.csv").write_text("id\\n1\\n2\\n", encoding="utf-8")
    (directory / "a.txt").write_bytes(b"source evidence")
    (directory / "nested").mkdir()
    (directory / "nested" / "c.json").write_text('{"source":"highergov"}', encoding="utf-8")
    first = snapshot_outputs(tmp_path, [rel])[rel]
    assert first.exists is True
    assert first.row_count == 2
    assert first.size_bytes == len(b"id\\n1\\n2\\n") + len(b"source evidence") + len(b'{"source":"highergov"}')
    assert len(first.sha256) == 64

    alternate = tmp_path / "alternate"
    other = alternate / rel
    other.mkdir(parents=True)
    (other / "a.txt").write_bytes(b"source evidence")
    (other / "b.csv").write_text("id\\n1\\n2\\n", encoding="utf-8")
    (other / "nested").mkdir()
    (other / "nested" / "c.json").write_text('{"source":"highergov"}', encoding="utf-8")
    assert snapshot_outputs(alternate, [rel])[rel].sha256 == first.sha256

    (directory / "b.csv").write_text("id\\n1\\n3\\n", encoding="utf-8")
    changed = snapshot_outputs(tmp_path, [rel])[rel]
    assert changed.row_count == 2
    assert changed.sha256 != first.sha256


def test_empty_directory_is_not_invented_as_a_materialized_row(tmp_path):
    rel = "data/raw/HigherGov"
    (tmp_path / rel).mkdir(parents=True)
    result = snapshot_outputs(tmp_path, [rel])[rel]
    assert result.exists is True
    assert result.size_bytes == 0
    assert result.row_count == 0
    assert len(result.sha256) == 64


def test_directory_snapshot_rejects_symlinks_and_path_escape(tmp_path):
    rel = "data/raw/HigherGov"
    directory = tmp_path / rel
    directory.mkdir(parents=True)
    outside = tmp_path / "private.txt"
    outside.write_text("not part of source output", encoding="utf-8")
    try:
        (directory / "alias.txt").symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(ValueError, match="unsafe directory output member"):
        snapshot_outputs(tmp_path, [rel])
    with pytest.raises(ValueError, match="escapes or aliases"):
        snapshot_outputs(tmp_path, ["../outside"])


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
