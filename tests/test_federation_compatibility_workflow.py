import importlib.util
import json
from pathlib import Path


WORKFLOW = Path(".github/workflows/federation-compatibility.yml")
RECEIPT = Path("governance/federation_compatibility.json")
CHECKER = Path(".federation/check_federation_compatibility.py")

spec = importlib.util.spec_from_file_location("federation_compatibility", CHECKER)
assert spec and spec.loader
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_federation_compatibility_workflow_pins_runtime_dependencies() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in text
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in text
    assert 'python-version: "3.12"' in text


def test_federation_compatibility_workflow_binds_push_commit_range() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.before" in text
    assert "github.sha" in text
    assert "python .federation/check_federation_compatibility.py" in text


def test_federation_compatibility_receipt_binds_exact_central_merge() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    assert checker.validate_receipt(receipt, "moneysweep-pr") == []
    assert receipt["central_governance_head_sha"] == "800d3cc719e5c71fff70fefa8214a4c34ab39fd6"
    assert receipt["central_governance_merge_sha"] == "58f06c38a143fcdf4277a501bc39929a0eb68f98"


def test_federation_compatibility_rejects_bad_identity_and_sha() -> None:
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))
    receipt["central_governance_repo"] = "wrong/repo"
    receipt["central_governance_head_sha"] = "not-a-sha"
    errors = checker.validate_receipt(receipt, "moneysweep-pr")
    assert "wrong central governance repository" in errors
    assert "invalid central_governance_head_sha" in errors


def test_federation_contract_drift_requires_receipt_update() -> None:
    watched = {"federation.json", "scripts/federation_export.py"}
    assert checker.validate_change_scope({"federation.json"}, watched)
    assert checker.validate_change_scope({"README.md"}, watched) == []
    assert (
        checker.validate_change_scope(
            {"scripts/federation_export.py", checker.RECEIPT_PATH}, watched
        )
        == []
    )
