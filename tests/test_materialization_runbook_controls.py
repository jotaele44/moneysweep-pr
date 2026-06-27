import json
from pathlib import Path

from scripts.check_network_egress import check_https_endpoint, run_checks

_ROOT = Path(__file__).resolve().parents[1]


def test_materialization_runbook_exists_and_names_automatable_target():
    path = _ROOT / "docs" / "MATERIALIZATION_RUNBOOK.md"
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "automatable" in text
    assert "reports/materialization_readiness.json" in text
    assert "coverage_rate" in text


def test_materialization_operator_checklist_exists():
    path = _ROOT / "docs" / "MATERIALIZATION_OPERATOR_CHECKLIST.md"
    assert path.exists()

    text = path.read_text(encoding="utf-8")
    assert "Pre-Run Checklist" in text
    assert "Run Checklist" in text
    assert "Post-Run Checklist" in text
    assert "No secrets are committed" in text


def test_materialization_readiness_snapshot_matches_runbook_counts():
    snapshot = json.loads(
        (_ROOT / "reports" / "materialization_readiness.json").read_text(encoding="utf-8")
    )

    # 13 formerly scraper_needed sources promoted to api_producer after confirming
    # their producer scripts are importable with real scraping implementations.
    # Only hacienda_sut_ivu and pr_act_154_excise remain scraper_needed (true stubs).
    # Counts below are pinned to the regenerated reports/materialization_readiness.json.
    assert snapshot["total_sources"] == 141
    assert snapshot["automatable_total"] == 95
    assert snapshot["automatable_ready"] == 95
    assert snapshot["queued_excluded_total"] == 46
    assert snapshot["automatable_not_ready"] == []


def test_egress_checker_invalid_url_fails_without_network():
    result = check_https_endpoint("http://not-https.example")
    assert result.ok is False
    assert result.error == "invalid https url"


def test_egress_checker_run_checks_reports_blocked_for_invalid_endpoint():
    result = run_checks(["http://not-https.example"])
    assert result["ok"] is False
    assert len(result["checked"]) == 1
    assert len(result["blocked"]) == 1
    assert result["blocked"][0]["error"] == "invalid https url"
