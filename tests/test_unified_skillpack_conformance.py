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

    def test_spatial_scope_remains_exact(self) -> None:
        # main removed the repo-wide change-freeze this test used to exercise
        # (see governance/change_log.json): is_allowed_path is gone and
        # allowed_change_paths is now a passive record. Do not reinstate that
        # enforcement here. The property this attestation still owns is that the
        # entries it added are exact files, not a widened directory or a glob.
        manifest = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())
        allowed = manifest["allowed_change_paths"]
        for spatial_path in (
            "federation/spatial/grid_manifest.json",
            "federation/spatial/geometry_manifest.json",
            "federation/spatial/registry_version.json",
        ):
            self.assertIn(spatial_path, allowed)
        self.assertNotIn("federation/spatial/", allowed)
        for entry in allowed:
            self.assertNotIn("*", entry, entry)
            if entry.endswith("/"):
                self.assertEqual(entry, ".claude/skillpacks/", entry)

    def test_spatial_disposition_does_not_replace_repo_compatibility(self) -> None:
        receipt = json.loads((ROOT / "governance/federation_compatibility.json").read_text())
        self.assertEqual(receipt["disposition"], "COMPATIBLE")
        self.assertEqual(receipt["spatial_disposition"], "ATTESTED")


if __name__ == "__main__":
    unittest.main()
