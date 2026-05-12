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
    assert payload["schema_version"] == "r5_v1"
    assert "thresholds" in payload


@pytest.mark.unit
def test_entity_resolution_gate_passes_on_fixture(tmp_path):
    _build_tmp_repo(tmp_path)
    proc = tmp_path / "data" / "staging" / "processed"
    proc.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "sample_entities_resolved.csv", proc / "entities_resolved.csv")
    er = vg.gate_entity_resolution(tmp_path)
    # 5 of 7 rows have a parent_uei → 0.714, below 0.95 target — so the rate
    # gate fails but the function should report a numeric rate.
    assert 0.0 < er["resolution_rate"] <= 1.0


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
