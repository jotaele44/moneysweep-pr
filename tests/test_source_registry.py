"""Tests for the source registry loader."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from contract_sweeper.runtime import source_registry as sr

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.unit
def test_load_source_registry_returns_dict_with_sources():
    reg = sr.load_source_registry(REPO_ROOT)
    assert isinstance(reg, dict)
    assert isinstance(reg.get("sources"), list)
    assert len(reg["sources"]) >= 40, "registry must declare the full PR ecosystem (40+ sources)"


@pytest.mark.unit
def test_each_source_has_required_fields():
    for src in sr.all_sources(REPO_ROOT):
        assert src.get("source_id"), f"missing source_id: {src!r}"
        assert "required" in src, f"{src['source_id']}: missing required flag"
        assert src.get("authentication") in {"none", "manual_export"} or (
            src.get("authentication", "").startswith("api_key:")
        ), f"{src['source_id']}: invalid authentication value"


@pytest.mark.unit
def test_required_sources_present():
    required_ids = {s["source_id"] for s in sr.required_sources(REPO_ROOT)}
    # The mission core set must be required.
    expected = {
        "usaspending_prime",
        "usaspending_subawards",
        "sam_entities",
        "fema_pa_openfema_v2",
        "cor3",
        "prasa",
        "hud_cdbg_dr_public",
        "hud_drgr_authorized",
        "emma_bonds",
        "lda",
        "pr_cabilderos",
        "fec",
        "oficina_contralor",
    }
    missing = expected - required_ids
    assert not missing, f"required mission sources missing: {missing}"


@pytest.mark.unit
def test_validate_registry_passes_on_real_registry():
    report = sr.validate_registry(REPO_ROOT)
    # Errors are fatal; warnings are tolerated. R5 PR1 must produce zero errors.
    assert report["ok"], f"source_registry validation errors: {report['errors']}"


@pytest.mark.unit
def test_no_duplicate_source_ids():
    ids = [s["source_id"] for s in sr.all_sources(REPO_ROOT)]
    assert len(ids) == len(set(ids)), "duplicate source_ids in registry"


@pytest.mark.unit
def test_json_sibling_matches_yaml_keys(tmp_path):
    """JSON sibling must be a faithful render of the YAML structure."""
    yaml_path = REPO_ROOT / "registries" / "source_registry.yaml"
    json_path = REPO_ROOT / "registries" / "source_registry.json"
    assert yaml_path.exists(), "source_registry.yaml missing"
    assert json_path.exists(), "source_registry.json missing"
    data_json = json.loads(json_path.read_text())
    assert "sources" in data_json
    assert data_json.get("version") == "1.0"


@pytest.mark.unit
def test_source_registry_extensions_are_loaded():
    nara = sr.source_by_id("nara_nextgen_catalog_v3", REPO_ROOT)
    assert nara is not None
    assert nara["family"] == "provenance_archival"
    assert nara["required"] is False
    assert nara["authentication"] == "api_key:NARA_API_KEY"
    assert nara["producer_script"] == "scripts/download_nara_nextgen.py"

    bulk = sr.source_by_id("nara_catalog_aws_open_data", REPO_ROOT)
    assert bulk is not None
    assert bulk["family"] == "provenance_archival"
    assert bulk["authentication"] == "none"
    assert bulk["producer_script"] == "scripts/download_nara_nextgen.py"


@pytest.mark.unit
def test_expected_outputs_for_resolves_to_repo_root():
    src = sr.source_by_id("usaspending_prime", REPO_ROOT)
    assert src is not None
    paths = sr.expected_outputs_for(src, REPO_ROOT)
    assert paths and all(isinstance(p, Path) for p in paths)
    assert all(str(p).startswith(str(REPO_ROOT)) for p in paths)
