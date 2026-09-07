from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "validate_unified_skillpacks", ROOT / "tools" / "validate_unified_skillpacks.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def validate_with_changed_path(changed_path: str) -> dict:
    def fake_run_git(_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        if args[:2] == ("rev-parse", "--is-shallow-repository"):
            return subprocess.CompletedProcess(args, 0, "false\n", "")
        if args[0] == "diff":
            return subprocess.CompletedProcess(args, 0, f"{changed_path}\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    with patch.object(MODULE, "run_git", side_effect=fake_run_git):
        return MODULE.validate(
            ROOT,
            enforce_change_scope=True,
            change_base="0" * 40,
        )


class UnifiedSkillpackConformanceTests(unittest.TestCase):
    def test_full_conformance(self) -> None:
        result = MODULE.validate(ROOT)
        self.assertEqual(result["status"], "success", result["errors"])

    def test_change_scope_can_use_current_integration_base(self) -> None:
        head = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        result = MODULE.validate(ROOT, enforce_change_scope=True, change_base=head)
        self.assertEqual(result["status"], "success", result["errors"])
        self.assertIn("change_base_ancestry", result["checks"])

    def test_change_scope_accepts_paths_inside_manifest(self) -> None:
        result = validate_with_changed_path(".claude/skillpacks/SKILL.md")

        self.assertEqual(result["status"], "success", result["errors"])

    def test_change_scope_rejects_paths_outside_manifest(self) -> None:
        result = validate_with_changed_path("src/outside_scope.py")

        self.assertEqual(result["status"], "failed")
        self.assertIn("out-of-scope change: src/outside_scope.py", result["errors"])

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


if __name__ == "__main__":
    unittest.main()
