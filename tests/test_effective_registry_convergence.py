from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from moneysweep.runtime.source_registry import load_source_registry
from tools.operator_corpus_common import (
    load_sources,
    source_definition_digest,
    source_ids_digest,
)

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[1]
CURRENT_SOURCE_IDS_SHA256 = "4c551385f00ca6df4332ee1643d0ef7a6ab85172632d945d35be285cd94f5826"


def _write(root: Path, relative: str, value: object) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _source(*, endpoint: str = "https://example.invalid/base") -> dict:
    return {
        "source_id": "alpha",
        "family": "test",
        "required": True,
        "authentication": "none",
        "endpoint_url": endpoint,
        "producer_script": "scripts/alpha.py",
        "expected_outputs": ["data/alpha.csv"],
        "validation_threshold": {"min_rows": 1},
        "update_cadence": "daily",
    }


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    source = _source()
    _write(root, "registries/source_registry.json", {"sources": [source]})
    yaml_path = root / "registries/source_registry.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"sources": [_source(endpoint="https://example.invalid/yaml-only")]}, sort_keys=False),
        encoding="utf-8",
    )
    return root


def test_certification_uses_effective_runtime_json_definition_not_yaml_mirror(tmp_path: Path) -> None:
    root = _root(tmp_path)
    sources, paths = load_sources(root)

    assert sources[0]["endpoint_url"] == "https://example.invalid/base"
    assert "registries/source_registry.json" in paths
    assert "registries/source_registry.yaml" not in paths


def test_override_changes_effective_definition_and_receipt_digest(tmp_path: Path) -> None:
    root = _root(tmp_path)
    base = _source()
    base_digest = source_definition_digest(base)
    _write(
        root,
        "registries/source_registry_overrides/provenance.json",
        {"source_overrides": [{"source_id": "alpha", "official_custodian": "Authority"}]},
    )

    sources, paths = load_sources(root)
    assert sources[0]["official_custodian"] == "Authority"
    assert source_definition_digest(sources[0]) != base_digest
    assert "registries/source_registry_overrides/provenance.json" in paths


def test_json_extension_is_first_class_and_yaml_extension_is_not(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write(
        root,
        "registries/source_registry_extensions/beta.json",
        {"sources": [{**_source(), "source_id": "beta", "required": False}]},
    )
    yaml_extension = root / "registries/source_registry_extensions/discovery.yaml"
    yaml_extension.write_text(
        yaml.safe_dump({"sources": [{**_source(), "source_id": "gamma", "required": False}]}),
        encoding="utf-8",
    )

    sources, paths = load_sources(root)
    assert {source["source_id"] for source in sources} == {"alpha", "beta"}
    assert "registries/source_registry_extensions/beta.json" in paths
    assert "registries/source_registry_extensions/discovery.yaml" not in paths


def test_duplicate_json_keys_fail_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "registries/source_registry.json").write_text(
        '{"sources": [], "sources": []}\n', encoding="utf-8"
    )
    with pytest.raises(ValueError, match="duplicate JSON key"):
        load_source_registry(root)


def test_nonfinite_json_numbers_fail_closed(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (root / "registries/source_registry.json").write_text(
        '{"sources": [{"source_id":"alpha","required":true,"value":NaN}]}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="non-finite JSON number"):
        load_source_registry(root)


def test_override_cannot_change_required_or_target_unknown_source(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write(
        root,
        "registries/source_registry_overrides/bad.json",
        {"source_overrides": [{"source_id": "alpha", "required": False}]},
    )
    with pytest.raises(ValueError, match="may not change immutable field required"):
        load_source_registry(root)

    (root / "registries/source_registry_overrides/bad.json").unlink()
    _write(
        root,
        "registries/source_registry_overrides/bad.json",
        {"source_overrides": [{"source_id": "missing", "official_custodian": "X"}]},
    )
    with pytest.raises(ValueError, match="targets unknown source"):
        load_source_registry(root)


def test_current_repository_effective_registry_is_164_and_overrides_are_visible() -> None:
    sources, paths = load_sources(ROOT)
    by_id = {source["source_id"]: source for source in sources}

    assert len(sources) == 164
    assert source_ids_digest(sources) == CURRENT_SOURCE_IDS_SHA256
    assert by_id["cor3"]["live_endpoint_status"] == "UNVERIFIED_BEST_EFFORT"
    assert by_id["pr_cabilderos"]["official_custodian"] == "Puerto Rico Department of Justice"
    assert "registries/source_registry_overrides/wave0_provenance_corrections.json" in paths
    assert {"pr_fomb", "pr_fomb_special_reports"}.issubset(by_id)
