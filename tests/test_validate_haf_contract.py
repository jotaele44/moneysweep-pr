import json
import shutil
from pathlib import Path

from scripts.validate_haf_contract import CONTRACT, validate

REPO_ROOT = Path(__file__).resolve().parents[1]


def _contract_root(tmp_path: Path) -> Path:
    (tmp_path / CONTRACT.parent).mkdir(parents=True)
    shutil.copy2(REPO_ROOT / CONTRACT, tmp_path / CONTRACT)
    shutil.copy2(REPO_ROOT / "federation.json", tmp_path / "federation.json")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/federation_export.py").write_text("", encoding="utf-8")
    return tmp_path


def test_haf_contract_accepts_complete_repository_binding(tmp_path: Path) -> None:
    assert validate(_contract_root(tmp_path), "jotaele44/moneysweep-pr") == []


def test_haf_contract_rejects_false_canonical_export_claim(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    contract = json.loads((root / CONTRACT).read_text(encoding="utf-8"))
    contract["canonical_export_required"] = False
    (root / CONTRACT).write_text(json.dumps(contract), encoding="utf-8")
    assert any(
        "canonical_export_required" in error for error in validate(root, "jotaele44/moneysweep-pr")
    )


def test_haf_contract_rejects_missing_native_contract(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    (root / "federation.json").unlink()
    assert "native_contract does not resolve to a file" in validate(root, "jotaele44/moneysweep-pr")


def _rewrite_contract(root: Path, **updates: object) -> None:
    path = root / CONTRACT
    contract = json.loads(path.read_text(encoding="utf-8"))
    contract.update(updates)
    path.write_text(json.dumps(contract), encoding="utf-8")


def test_haf_contract_rejects_unearned_adapter_promotion(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    _rewrite_contract(root, adapter_state="COMPATIBLE")
    assert any("adapter_state" in error for error in validate(root, "jotaele44/moneysweep-pr"))


def test_haf_contract_rejects_command_not_bound_to_native_manifest(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    _rewrite_contract(root, canonical_export_command="echo pass")
    assert any(
        "canonical_export_command does not match" in error
        for error in validate(root, "jotaele44/moneysweep-pr")
    )


def test_haf_contract_rejects_native_identity_drift(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    native_path = root / "federation.json"
    native = json.loads(native_path.read_text(encoding="utf-8"))
    native["repository_full_name"] = "jotaele44/not-moneysweep-pr"
    native_path.write_text(json.dumps(native), encoding="utf-8")
    assert any(
        "native contract repository_full_name" in error
        for error in validate(root, "jotaele44/moneysweep-pr")
    )


def test_haf_contract_rejects_invalid_native_json(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    (root / "federation.json").write_text("{", encoding="utf-8")
    assert any(
        "invalid native contract" in error for error in validate(root, "jotaele44/moneysweep-pr")
    )


def test_haf_contract_rejects_missing_command_script(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    (root / "scripts/federation_export.py").unlink()
    assert any(
        "canonical_export_command references a missing script" in error
        for error in validate(root, "jotaele44/moneysweep-pr")
    )


def test_haf_contract_rejects_malformed_command(tmp_path: Path) -> None:
    root = _contract_root(tmp_path)
    malformed = "python3 'unterminated"
    _rewrite_contract(root, canonical_export_command=malformed)
    native_path = root / "federation.json"
    native = json.loads(native_path.read_text(encoding="utf-8"))
    native["hub_callable_commands"]["export_canonical"] = malformed
    native_path.write_text(json.dumps(native), encoding="utf-8")
    assert any(
        "canonical_export_command is malformed" in error
        for error in validate(root, "jotaele44/moneysweep-pr")
    )
