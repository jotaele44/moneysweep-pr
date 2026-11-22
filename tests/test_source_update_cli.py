"""CLI + executor-isolation tests for the source update controller."""

from __future__ import annotations

import json

import pytest

from moneysweep.update_controller import cli
from moneysweep.update_controller.executor import run_source, run_source_isolated
from moneysweep.update_controller.models import FreshnessResult, SourceUpdatePolicy
from moneysweep.update_controller.policy import canonical_source_ids
from moneysweep.update_controller.validation import freshness_exit_code

pytestmark = pytest.mark.unit

EXPECTED_SOURCE_COUNT = len(canonical_source_ids())


def _run_cli(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr().out
    return code, out


def test_validate_policy_exit_zero(capsys):
    code, _out = _run_cli(["validate-policy", "--json"], capsys)
    assert code == 0


def test_plan_json_is_valid_and_read_only(capsys):
    code, out = _run_cli(["plan", "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["selected"] == EXPECTED_SOURCE_COUNT
    assert "plan" in payload


def test_plan_due_excludes_manual_and_disabled(capsys):
    _code, out = _run_cli(["plan", "--due", "--json"], capsys)
    payload = json.loads(out)
    for item in payload["plan"]:
        assert item["trigger_type"] not in ("manual", "disabled")


def test_state_command(capsys):
    code, out = _run_cli(["state", "--json"], capsys)
    assert code == 0
    payload = json.loads(out)
    assert payload["registry_snapshot"]["source_count"] == EXPECTED_SOURCE_COUNT


def test_run_parser_defaults_to_four_workers():
    args = cli.build_parser().parse_args(["run"])
    assert args.workers == 4


def test_run_parser_accepts_worker_override():
    args = cli.build_parser().parse_args(["run", "--workers", "2"])
    assert args.workers == 2


# --- executor isolation / gating (no network) ---
def _fake_root(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path


def _pol(sid, runner, trigger="schedule", secrets=None):
    return SourceUpdatePolicy(
        source_id=sid,
        trigger_type=trigger,
        enabled=(trigger != "disabled"),
        runner=runner,
        freshness_sla_hours=192,
        timeout_minutes=1,
        max_retries=0,
        empty_result_policy="preserve_previous",
        cadence="weekly",
        required_secrets=list(secrets or []),
    )


def test_disabled_source_cannot_run(tmp_path):
    root = _fake_root(tmp_path)
    pol = _pol("d", "scripts/none.py", trigger="disabled")
    state = {"sources": {}}
    res = run_source(
        pol, {"source_id": "d", "expected_outputs": []}, state, root=root, strict=False
    )
    assert res["status"] == "DISABLED"


def test_missing_secret_reports_status(tmp_path):
    root = _fake_root(tmp_path)
    pol = _pol("s", "scripts/x.py", secrets=["NOPE_API_KEY"])
    state = {"sources": {}}
    res = run_source(
        pol, {"source_id": "s", "expected_outputs": []}, state, root=root, dotenv={}, strict=False
    )
    assert res["status"] == "MISSING_SECRET"


def test_continue_on_error_isolates_failures(tmp_path):
    root = _fake_root(tmp_path)
    # one failing producer, one succeeding producer
    (root / "scripts" / "boom.py").write_text("import sys; sys.exit(1)\n")
    (root / "scripts" / "ok.py").write_text(
        "from pathlib import Path; Path('data/ok.csv').write_text('a\\n1\\n2\\n')\n"
    )
    state = {"sources": {}}
    bad = run_source(
        _pol("bad", "scripts/boom.py"),
        {"source_id": "bad", "expected_outputs": ["data/bad.csv"]},
        state,
        root=root,
        strict=False,
    )
    good = run_source(
        _pol("good", "scripts/ok.py"),
        {
            "source_id": "good",
            "expected_outputs": ["data/ok.csv"],
            "validation_threshold": {"min_rows": 1},
        },
        state,
        root=root,
        strict=False,
    )
    assert bad["status"] in ("PRODUCER_EXECUTION_FAILED", "PRODUCER_IMPORT_FAILED")
    assert good["status"] == "SUCCESS_WITH_CHANGE"  # failure of `bad` did not affect `good`


def test_failed_run_preserves_previous_output(tmp_path):
    root = _fake_root(tmp_path)
    # pre-existing valid output
    (root / "data" / "keep.csv").write_text("a\n1\n2\n3\n")
    (root / "scripts" / "boom.py").write_text("import sys; sys.exit(1)\n")
    state = {"sources": {}}
    run_source(
        _pol("k", "scripts/boom.py"),
        {
            "source_id": "k",
            "expected_outputs": ["data/keep.csv"],
            "validation_threshold": {"min_rows": 1},
        },
        state,
        root=root,
        strict=False,
    )
    # prior output untouched
    assert (root / "data" / "keep.csv").read_text() == "a\n1\n2\n3\n"


# --- freshness exit codes ---
def _fr(status, required=True, enabled=True, age=None, sla=192):
    return FreshnessResult(
        source_id="x",
        trigger_type="schedule",
        enabled=enabled,
        required=required,
        path_type="api_producer",
        update_cadence="weekly",
        freshness_sla_hours=sla,
        last_success_at=None,
        last_materialized_at=None,
        age_hours=age,
        freshness_status=status,
        next_due_at=None,
        consecutive_failures=0,
        last_status="NEVER_RUN",
    )


def test_freshness_exit_codes():
    assert freshness_exit_code([_fr("FRESH")]) == 0
    assert freshness_exit_code([_fr("NEVER_MATERIALIZED")]) == 1
    assert freshness_exit_code([_fr("DUE", required=False)]) == 1
    assert freshness_exit_code([_fr("STALE", required=True)]) == 2


def test_is_run_failure_classification():
    # successes + benign non-runs are not failures
    for ok in (
        "SUCCESS_WITH_CHANGE",
        "SUCCESS_NO_CHANGE",
        "EMPTY_EXPECTED",
        "CHECKPOINTED",
        "PLANNED",
        "DISABLED",
        "NOT_DUE",
        "MANUAL_INPUT_MISSING",
        "DEPENDENCY_NOT_READY",
        "MISSING_SECRET",
    ):
        assert cli.is_run_failure(ok) is False, ok
    # real failures (incl. those an auto-triggered dependent can return) count
    for bad in (
        "PRODUCER_EXECUTION_FAILED",
        "PRODUCER_IMPORT_FAILED",
        "OUTPUT_MISSING",
        "OUTPUT_REGRESSION",
        "SCHEMA_FAILED",
        "FRESHNESS_FAILED",
    ):
        assert cli.is_run_failure(bad) is True, bad


def test_controller_crash_is_recorded_against_one_source_only(tmp_path, monkeypatch):
    """A snapshot error on one source must not abort the rest of the cadence."""
    from moneysweep.update_controller import executor

    root = _fake_root(tmp_path)
    (root / "scripts" / "ok.py").write_text(
        "from pathlib import Path; Path('data/ok.csv').write_text('a\\n1\\n2\\n')\n"
    )
    real = executor.snapshot_outputs

    def explode_on_bad(root_, expected):
        if expected == ["data/bad.csv"]:
            raise IsADirectoryError("data/bad.csv")
        return real(root_, expected)

    monkeypatch.setattr(executor, "snapshot_outputs", explode_on_bad)
    state = {"sources": {}}
    bad = run_source_isolated(
        _pol("bad", "scripts/ok.py"),
        {"source_id": "bad", "expected_outputs": ["data/bad.csv"]},
        state,
        root=root,
        strict=False,
    )
    good = run_source_isolated(
        _pol("good", "scripts/ok.py"),
        {
            "source_id": "good",
            "expected_outputs": ["data/ok.csv"],
            "validation_threshold": {"min_rows": 1},
        },
        state,
        root=root,
        strict=False,
    )
    assert bad["status"] == "PRODUCER_EXECUTION_FAILED"
    assert bad["failure_packet"]["suspected_area"] == "update_controller"
    assert "IsADirectoryError" in bad["failure_packet"]["last_40_lines"][0]
    assert state["sources"]["bad"]["consecutive_failures"] == 1
    assert good["status"] == "SUCCESS_WITH_CHANGE"
