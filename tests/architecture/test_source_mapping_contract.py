from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "architecture" / "v4" / "source_mapping_contract.yaml"


def _load_contract():
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))


def _family_examples(data):
    return {
        (item["family"], item["target_type"], item["capability"])
        for item in data["regression"]["positive_examples"]
        if "family" in item
    }


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
    examples = _family_examples(_load_contract())
    assert ("entity_resolution", "CORE_SUPPORT", "IDENTITY_RESOLUTION") in examples
    assert ("provenance_archival", "CORE_SUPPORT", "PROVENANCE_ARCHIVAL") in examples


def test_cross_domain_context_support_classes_exist():
    data = _load_contract()
    assert "POLICY_CONTEXT" in data["core_support_capabilities"]
    assert "PRE_OFFICIAL_CANDIDATE" in data["core_support_capabilities"]
    examples = _family_examples(data)
    assert ("territorial_legislation", "CORE_SUPPORT", "POLICY_CONTEXT") in examples
    assert ("pre_officialization", "CORE_SUPPORT", "PRE_OFFICIAL_CANDIDATE") in examples
