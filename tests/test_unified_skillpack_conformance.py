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

    def test_unrelated_later_commits_do_not_expand_skillpack_scope(self) -> None:
        allowed = json.loads((ROOT / ".claude/skillpacks/MANIFEST.json").read_text())["allowed_change_paths"]
        changed = MODULE.scoped_change_paths(
            ROOT,
            json.loads((ROOT / ".claude/skillpacks/BINDING.json").read_text())["pinned_base_commit"],
            allowed,
        )
        self.assertNotIn("docs/BACKEND_ASSESSMENT_AND_DEVELOPMENT_PLAN.md", changed)
        self.assertNotIn("scripts/desktop_startup_probe.py", changed)
        self.assertTrue(all(MODULE.is_allowed_path(path, allowed) for path in changed))


if __name__ == "__main__":
    unittest.main()
