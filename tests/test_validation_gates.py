"""Tests for the R5 validation gates."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from contract_sweeper.runtime import validation_gates as vg

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r5"


def _build_tmp_repo(tmp_path: Path) -> None:
    """Lay a minimal repo with the registries copied across so gates can run."""
    repo_root = Path(__file__).resolve().parents[1]
    (tmp_path / "registries").mkdir(parents=True, exist_ok=True)
    for name in ("source_registry.json", "schema_registry.json"):
        shutil.copy(repo_root / "registries" / name, tmp_path / "registries" / name)
    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    shutil.copy(repo_root / "scripts" / "scan_for_secrets.py", tmp_path / "scripts" / "scan_for_secrets.py")
    # Copy every producer_script as an empty placeholder so registry validation passes
    reg = json.loads((tmp_path / "registries" / "source_registry.json").read_text())
    for src in reg.get("sources", []):
        script = src.get("producer_script")
        if not script:
            continue
        target = tmp_path / script
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text(f"# placeholder for {src['source_id']}\n", encoding="utf-8")


@pytest.mark.unit
def test_evaluate_with_no_data_reports_failures(tmp_path):
    _build_tmp_repo(tmp_path)
    report = vg.evaluate(tmp_path)
    assert report["passed"] is False
    assert report["failed_gate_count"] >= 1
    assert "source_coverage_rate" in report
    assert "entity_resolution_rate" in report


@pytest.mark.unit
def test_write_report_emits_canonical_paths(tmp_path):
    _build_tmp_repo(tmp_path)
    report = vg.evaluate(tmp_path)
    paths = vg.write_report(tmp_path, report)
    assert paths["json"] == tmp_path / "data" / "manifests" / "validation_report.json"
    assert paths["csv"] == tmp_path / "data" / "manifests" / "validation_gate_report.csv"
    assert paths["json"].exists()
    payload = json.loads(paths["json"].read_text())
    assert payload["schema_version"] == "r5_v2"
    assert "thresholds" in payload
    assert "entity_type_assignment_rate" in payload["thresholds"]
    assert "corporate_parent_uei_rate" in payload["thresholds"]


@pytest.mark.unit
def test_entity_resolution_gate_passes_on_fixture(tmp_path):
    _build_tmp_repo(tmp_path)
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "sample_entities_resolved.csv", proc / "entities_resolved.csv")
    er = vg.gate_entity_resolution(tmp_path)
    # 5 of 7 corporate rows have parent_uei → resolution_rate > 0
    assert 0.0 < er["resolution_rate"] <= 1.0
    # entity_type_assignment_rate: all 9 rows have entity_type → should be 1.0
    assert er["entity_type_assignment_rate"] == 1.0
    # corporate_parent_uei_rate: 5 of 7 corporate entities → ~0.71
    assert er["corporate_parent_uei_rate"] > 0.5


@pytest.mark.unit
def test_entity_type_assignment_gate_passes_when_all_typed(tmp_path):
    _build_tmp_repo(tmp_path)
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "sample_entities_resolved.csv", proc / "entities_resolved.csv")
    er = vg.gate_entity_resolution(tmp_path)
    type_gate = next(r for r in er["records"] if r["gate"] == "entity_type_assignment_rate")
    assert type_gate["passed"] is True
    assert type_gate["observed"] == 1.0


@pytest.mark.unit
def test_corporate_parent_uei_gate_excludes_government_entities(tmp_path):
    """Government entities in the fixture must not dilute corporate_parent_uei_rate."""
    _build_tmp_repo(tmp_path)
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "sample_entities_resolved.csv", proc / "entities_resolved.csv")
    er = vg.gate_entity_resolution(tmp_path)
    # Fixture has 7 corporate + 1 government + 1 nonprofit.
    # 5 of 7 corporate have parent_uei → rate = 5/7 ≈ 0.714
    # Government and nonprofit entities must not be counted in the denominator.
    corp_rate = er["corporate_parent_uei_rate"]
    assert 0.70 < corp_rate < 0.75, f"unexpected rate: {corp_rate}"


@pytest.mark.unit
def test_high_value_review_gate_passes_when_queue_populated(tmp_path):
    """high_value_unresolved_review_rate passes when unresolved entities are in review_queue."""
    _build_tmp_repo(tmp_path)
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    rq = tmp_path / "data" / "review_queue"
    rq.mkdir(parents=True, exist_ok=True)
    # Write a high_value_unresolved with 2 rows
    hvu_rows = [
        {"entity_id": "A1", "total_obligation": "2000000", "entity_name": "Acme"},
        {"entity_id": "A2", "total_obligation": "1500000", "entity_name": "Beta"},
    ]
    _write_csv_simple(proc / "high_value_unresolved.csv", hvu_rows)
    # Write review_queue with both entity_ids present
    _write_csv_simple(rq / "pr2_unresolved_entities.csv", hvu_rows)
    # Also write a minimal entities_resolved so the gate doesn't return early
    _write_csv_simple(proc / "entities_resolved.csv", [
        {"entity_id": "A1", "entity_type": "corporate", "parent_uei": "", "parent_name": "", "total_obligation": "2000000"},
    ])
    er = vg.gate_entity_resolution(tmp_path)
    rv_gate = next((r for r in er["records"] if r["gate"] == "high_value_unresolved_review_rate"), None)
    assert rv_gate is not None
    assert rv_gate["passed"] is True
    assert rv_gate["observed"] == 1.0


def _write_csv_simple(path: Path, rows: list[dict]) -> None:
    import csv
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)


@pytest.mark.unit
def test_main_exits_2_when_gates_fail_without_allow_failed(tmp_path):
    _build_tmp_repo(tmp_path)
    exit_code = vg.main(["--root", str(tmp_path)])
    assert exit_code == 2


@pytest.mark.unit
def test_main_exits_0_with_allow_failed(tmp_path):
    _build_tmp_repo(tmp_path)
    exit_code = vg.main(["--root", str(tmp_path), "--allow-failed"])
    assert exit_code == 0


@pytest.mark.unit
def test_entity_resolution_gate_passes_low_rate_pr_data(tmp_path):
    """entity_resolution_rate of ~0.4 % (realistic PR gov data) must PASS at canary threshold."""
    _build_tmp_repo(tmp_path)
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    # 1 000 entities; only 5 have parent_uei (0.5 %) — matches real PR universe
    rows = [
        {"entity_id": f"E{i:04d}", "entity_type": "government", "parent_uei": "", "parent_name": ""}
        for i in range(995)
    ] + [
        {"entity_id": f"C{i:04d}", "entity_type": "corporate", "parent_uei": f"PUEI{i}", "parent_name": f"Parent {i}"}
        for i in range(5)
    ]
    _write_csv_simple(proc / "entities_resolved.csv", rows)
    er = vg.gate_entity_resolution(tmp_path)
    rate_gate = next(r for r in er["records"] if r["gate"] == "entity_resolution_rate")
    # 5/1000 = 0.005 > threshold 0.001 → must pass
    assert rate_gate["passed"] is True, f"entity_resolution_rate should pass at 0.005 (threshold 0.001); got {rate_gate}"


@pytest.mark.unit
def test_manifest_gate_skips_unmaterialized_sources(tmp_path):
    """manifest_present_per_required must not flag sources with no output files."""
    _build_tmp_repo(tmp_path)
    # No expected_output files exist anywhere → all required sources are unmaterialized
    result = vg.gate_manifests_present(tmp_path)
    # Every required source is unmaterialized, so the gate produces no records at all
    assert result["records"] == [], (
        "gate_manifests_present should produce no records when no source has been materialized"
    )


@pytest.mark.unit
def test_duplicate_rate_gate_skips_raw_input_files(tmp_path):
    """duplicate_rate gate must not fire for files outside data/staging/processed/."""
    _build_tmp_repo(tmp_path)
    (tmp_path / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    # Build a fake canonical manifest with one raw file (high dup rate) and one processed file (clean)
    raw_entry = {
        "relative_path": "data/staging/raw/grants/direct_recipient_fy2008.csv",
        "source_system": "unknown",
        "duplicate_rate": 34.51,
        "pk_field": "award_id",
    }
    processed_entry = {
        "relative_path": "data/staging/processed/pr_contracts_master.csv",
        "source_system": "usaspending_prime",
        "duplicate_rate": 0.0,
        "pk_field": "award_id",
    }
    manifest = {"files": [raw_entry, processed_entry]}
    (tmp_path / "data" / "manifests" / "source_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    result = vg.gate_duplicate_rate(tmp_path)
    source_ids = [r.get("source_id") for r in result["records"]]
    assert "unknown" not in source_ids, "raw file with source_system=unknown must be skipped"
    assert any(r.get("source_id") == "usaspending_prime" for r in result["records"]), (
        "processed file must still be checked"
    )


@pytest.mark.unit
def test_duplicate_rate_gate_skips_review_queue_and_exports(tmp_path):
    """Files in review_queue/ and exports/ must also be excluded from the gate."""
    _build_tmp_repo(tmp_path)
    (tmp_path / "data" / "manifests").mkdir(parents=True, exist_ok=True)
    entries = [
        {"relative_path": "data/review_queue/suspect_entities.csv", "source_system": "unknown", "duplicate_rate": 0.5},
        {"relative_path": "data/exports/rebuild_status.csv", "source_system": "unknown", "duplicate_rate": 0.3},
    ]
    (tmp_path / "data" / "manifests" / "source_manifest.json").write_text(
        json.dumps({"files": entries}), encoding="utf-8"
    )
    result = vg.gate_duplicate_rate(tmp_path)
    # No processed files → gate emits the "no pk yet" pass record
    assert len(result["records"]) == 1
    assert result["records"][0]["passed"] is True


@pytest.mark.unit
def test_manifest_gate_fires_only_for_materialized_sources(tmp_path):
    """manifest_present_per_required fires exactly for sources whose output files exist."""
    _build_tmp_repo(tmp_path)
    reg = json.loads((tmp_path / "registries" / "source_registry.json").read_text())
    # Find a required source with at least one expected_output and plant a fake file there
    required = [s for s in reg.get("sources", []) if s.get("required") and s.get("expected_outputs")]
    assert required, "need at least one required source with expected_outputs for this test"
    src = required[0]
    fake_output = tmp_path / src["expected_outputs"][0]
    fake_output.parent.mkdir(parents=True, exist_ok=True)
    fake_output.write_text("col\nval\n", encoding="utf-8")
    result = vg.gate_manifests_present(tmp_path)
    # Only the one source we planted a file for should appear
    assert len(result["records"]) == 1
    assert result["records"][0]["source_id"] == src["source_id"]
    assert result["records"][0]["passed"] is False  # no manifest directory yet
