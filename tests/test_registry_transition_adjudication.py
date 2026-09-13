import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports/registry_transition_adjudication_20260913.json"


def _report() -> dict:
    return json.loads(REPORT.read_text(encoding="utf-8"))


def test_source_set_arithmetic_and_exact_difference_close() -> None:
    report = _report()
    sets = report["source_id_sets"]
    assert sets["A_ONLY"] == []
    assert sets["B_ONLY"] == ["pr_fomb", "pr_fomb_special_reports"]
    assert sets["SYMMETRIC_DIFFERENCE"] == sets["B_ONLY"]
    assert sets["INTERSECTION_count"] == 162
    assert sets["UNION_count"] == 164
    assert report["A"]["source_count"] + report["B"]["source_count"] == 326
    assert sets["UNION_count"] + sets["INTERSECTION_count"] == 326
    assert (
        report["A"]["source_count"] + report["B"]["source_count"]
        == sets["UNION_count"] + sets["INTERSECTION_count"]
    )
    assert len(sets["SYMMETRIC_DIFFERENCE"]) == 2


def test_required_population_is_exactly_unchanged() -> None:
    report = _report()
    required = report["required_id_sets"]
    assert len(required["INTERSECTION"]) == 16
    assert required["A_ONLY"] == []
    assert required["B_ONLY"] == []
    assert required["SYMMETRIC_DIFFERENCE"] == []


def test_automatable_and_excluded_arithmetic_closes() -> None:
    report = _report()
    assert report["A"]["automatable_count"] + report["A"]["excluded_count"] == 162
    assert report["B"]["automatable_count"] + report["B"]["excluded_count"] == 164
    assert report["automatable_transition"]["delta"] == 3
    assert report["excluded_transition"]["delta"] == -1
    assert report["automatable_transition"]["promoted_existing_ids"] == ["hacienda_sut_ivu"]


def test_changed_definitions_never_inherit_receipts() -> None:
    report = _report()
    assert len(report["existing_source_definition_changes"]) == 5
    assert all(
        item["receipt_inheritance"] == "PROHIBITED"
        for item in report["existing_source_definition_changes"]
    )
    assert report["certification_effect"]["old_receipts_inherit_across_changed_definitions"] is False


def test_loader_profile_divergence_fails_closed() -> None:
    report = _report()
    profiles = report["loader_profiles"]
    assert profiles["source_id_symmetric_difference_at_B"] == []
    assert profiles["definition_difference_at_B"] == ["cor3", "pr_cabilderos"]
    assert profiles["decision"] == "PROFILES_NOT_EQUIVALENT"
    assert report["production_eligible"] is False
    assert report["state"] == "AUDIT_ONLY"
