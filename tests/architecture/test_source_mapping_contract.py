from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "architecture" / "v4" / "source_mapping_contract.yaml"


def _load_contract():
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def test_source_mapping_contract_supports_core_support():
    data = _load_contract()
    assert "DOMAIN" in data["target_types"]
    assert "CORE_SUPPORT" in data["target_types"]
    assert "IDENTITY_RESOLUTION" in data["core_support_capabilities"]
    assert "PROVENANCE_ARCHIVAL" in data["core_support_capabilities"]


def test_core_support_is_not_an_analytical_domain():
    data = _load_contract()
    rules = "\n".join(data["rules"])
    assert "not an analytical domain" in rules


def test_regression_examples_cover_repository_falsifier():
    data = _load_contract()
    examples = {
        (x["family"], x["target_type"], x["capability"])
        for x in data["regression"]["positive_examples"]
    }
    assert ("entity_resolution", "CORE_SUPPORT", "IDENTITY_RESOLUTION") in examples
    assert ("provenance_archival", "CORE_SUPPORT", "PROVENANCE_ARCHIVAL") in examples
