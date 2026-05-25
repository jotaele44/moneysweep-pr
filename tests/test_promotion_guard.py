"""Tests for the master-promotion guard (issue #86)."""

from __future__ import annotations

import json
from pathlib import Path

from contract_sweeper.validation.promotion_guard import (
    evaluate_promotion,
    run_guard,
)


def _validated_status(**overrides):
    base = {
        "production_status": "PRODUCTION_VALIDATED",
        "pause_lock_active": False,
        "last_tests": {"status": "GREEN", "failed": 0},
        "secrets_audit": {"findings": 0, "real_keys_in_repo": False},
    }
    base.update(overrides)
    return base


def _passing_gate():
    return {"production_status": "PRODUCTION_VALIDATED", "blocker_count": 0}


def test_diagnostic_status_is_eligible_without_evidence():
    result = evaluate_promotion({"production_status": "NON_PRODUCTION_DIAGNOSTIC"}, {})
    assert result["eligible"] is True
    assert result["promotion_claimed"] is False
    assert result["unmet_conditions"] == []


def test_missing_status_defaults_to_diagnostic_and_passes():
    result = evaluate_promotion({}, {})
    assert result["eligible"] is True
    assert result["promotion_claimed"] is False


def test_source_coverage_tiers_treated_as_diagnostic():
    for tier in ("PARTIAL_AVAILABLE_SOURCE_COVERAGE", "COMPLETE_AVAILABLE_SOURCE_COVERAGE"):
        result = evaluate_promotion({"production_status": tier}, {})
        assert result["eligible"] is True, tier


def test_fully_evidenced_validated_build_is_eligible():
    result = evaluate_promotion(_validated_status(), _passing_gate())
    assert result["eligible"] is True
    assert result["promotion_claimed"] is True
    assert result["unmet_conditions"] == []


def test_blocked_when_pause_lock_active():
    result = evaluate_promotion(_validated_status(pause_lock_active=True), _passing_gate())
    assert result["eligible"] is False
    assert any("pause_lock_active" in c for c in result["unmet_conditions"])


def test_blocked_when_tests_not_green():
    result = evaluate_promotion(
        _validated_status(last_tests={"status": "RED", "failed": 3}), _passing_gate()
    )
    assert result["eligible"] is False
    assert any("last_tests" in c for c in result["unmet_conditions"])


def test_blocked_when_secrets_audit_has_findings():
    result = evaluate_promotion(
        _validated_status(secrets_audit={"findings": 2, "real_keys_in_repo": True}),
        _passing_gate(),
    )
    assert result["eligible"] is False
    assert any("secrets_audit" in c for c in result["unmet_conditions"])


def test_blocked_when_production_gate_artifact_missing():
    result = evaluate_promotion(_validated_status(), {})
    assert result["eligible"] is False
    assert any("production_status.json missing" in c for c in result["unmet_conditions"])


def test_blocked_when_production_gate_reports_blockers():
    gate = {"production_status": "PRODUCTION_VALIDATED", "blocker_count": 4}
    result = evaluate_promotion(_validated_status(), gate)
    assert result["eligible"] is False
    assert any("blocker" in c for c in result["unmet_conditions"])


def test_blocked_when_gate_still_diagnostic():
    gate = {"production_status": "NON_PRODUCTION_DIAGNOSTIC", "blocker_count": 0}
    result = evaluate_promotion(_validated_status(), gate)
    assert result["eligible"] is False
    assert any("NON_PRODUCTION_DIAGNOSTIC" in c for c in result["unmet_conditions"])


def test_unknown_status_treated_as_promotion_claim():
    result = evaluate_promotion({"production_status": "SHIP_IT_NOW"}, {})
    assert result["promotion_claimed"] is True
    assert result["eligible"] is False


def test_run_guard_reads_repo_state(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "current_status.json").write_text(
        json.dumps({"production_status": "NON_PRODUCTION_DIAGNOSTIC"}), encoding="utf-8"
    )
    result = run_guard(tmp_path)
    assert result["eligible"] is True
    assert result["promotion_claimed"] is False


def test_run_guard_on_actual_repo_is_eligible():
    repo_root = Path(__file__).resolve().parent.parent
    result = run_guard(repo_root)
    assert result["eligible"] is True
