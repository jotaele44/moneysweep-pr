from __future__ import annotations
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_unified_skillpacks", ROOT / "tools" / "validate_unified_skillpacks.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


class UnifiedSkillpackConformanceTests(unittest.TestCase):
    def test_full_conformance(self) -> None:
        result = MODULE.validate(ROOT)
        self.assertEqual(result["status"], "success", result["errors"])

    def test_dispatch_metadata_is_complete(self) -> None:
        manifest = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())
        for capability in manifest["capabilities"]:
            self.assertTrue(capability.get("status"), capability["id"])
            self.assertTrue(capability.get("preserved_responsibility"), capability["id"])
            self.assertTrue(capability.get("anchor"), capability["id"])

    def test_compatibility_targets_resolve(self) -> None:
        ledger = json.loads((ROOT / ".claude/skillpacks/LEGACY_COMPATIBILITY.json").read_text())
        skill = (ROOT / ".claude/skillpacks/SKILL.md").read_text()
        for entry in ledger["entries"]:
            target = entry["unified_target"].split("#", 1)[1]
            self.assertIn(f'<a id="{target}"></a>', skill, entry["capability_id"])

    def test_spatial_architecture_allowlist_is_exact(self) -> None:
        manifest = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())
        allowed = manifest["allowed_change_paths"]
        intended = {
            "docs/SPATIAL_BINDING_CONTRACT_V1.md",
            "schemas/federation_spatial_identity_v1_1.schema.json",
            "schemas/federation_spatial_migration_receipt_v1_1.schema.json",
            "scripts/build_federation_spatial_bindings_v1_1.py",
            "tests/test_federation_spatial_bindings_v1_1.py",
        }
        self.assertTrue(intended.issubset(allowed))
        for near_miss in (
            "docs/SPATIAL_BINDING_CONTRACT_V1.md.bak",
            "schemas/federation_spatial_identity_v1_1.schema.json/extra",
            "scripts/build_federation_spatial_bindings_v1_1.pyc",
            "tests/test_federation_spatial_bindings_v1_1.py.bak",
        ):
            self.assertFalse(MODULE.is_allowed_path(near_miss, allowed), near_miss)


if __name__ == "__main__":
    unittest.main()
