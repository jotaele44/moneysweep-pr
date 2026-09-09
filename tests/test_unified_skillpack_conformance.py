from __future__ import annotations
import importlib.util
import json
import shutil
import subprocess
import tempfile
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
    def run_git(self, root: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    def build_history_fixture(
        self,
        root: Path,
        *,
        out_of_scope_introduction: bool = False,
        post_introduction_product_change: bool = True,
    ) -> tuple[str, str]:
        self.run_git(root, "init")
        self.run_git(root, "config", "user.name", "Skillpack Test")
        self.run_git(root, "config", "user.email", "skillpack@example.test")

        for path in ("moneysweep", "scripts", "skills", "tests", ".github/workflows"):
            (root / path).mkdir(parents=True, exist_ok=True)
        (root / "moneysweep/.keep").write_text("", encoding="utf-8")
        (root / "scripts/.keep").write_text("", encoding="utf-8")
        (root / "skills/.keep").write_text("", encoding="utf-8")
        (root / "run_all.py").write_text("", encoding="utf-8")
        self.run_git(root, "add", ".")
        self.run_git(root, "commit", "-m", "fixture base")
        base = self.run_git(root, "rev-parse", "HEAD")

        (root / "moneysweep/product_before.py").write_text("VALUE = 1\n", encoding="utf-8")
        self.run_git(root, "add", ".")
        self.run_git(root, "commit", "-m", "product change before skillpack")

        source_root = ROOT / ".claude/skillpacks"
        target_root = root / ".claude/skillpacks"
        target_root.mkdir(parents=True)
        for name in ("SKILL.md", "LEGACY_COMPATIBILITY.json"):
            shutil.copy2(source_root / name, target_root / name)
        for name in ("BINDING.json", "MANIFEST.json"):
            payload = json.loads((source_root / name).read_text(encoding="utf-8"))
            payload["pinned_base_commit"] = base
            (target_root / name).write_text(
                json.dumps(payload, separators=(",", ":")), encoding="utf-8"
            )
        (root / "tools").mkdir()
        (root / "tools/validate_unified_skillpacks.py").write_text("# fixture\n")
        (root / "tests/test_unified_skillpack_conformance.py").write_text("# fixture\n")
        (root / ".github/workflows/unified-skillpack-conformance.yml").write_text(
            "name: fixture\n", encoding="utf-8"
        )
        if out_of_scope_introduction:
            (root / "moneysweep/introduced_with_skillpack.py").write_text(
                "VALUE = 2\n", encoding="utf-8"
            )
        self.run_git(root, "add", ".")
        self.run_git(root, "commit", "-m", "introduce unified skillpack")
        introduction = self.run_git(root, "rev-parse", "HEAD")

        if post_introduction_product_change:
            (root / "moneysweep/product_after.py").write_text("VALUE = 3\n", encoding="utf-8")
            self.run_git(root, "add", ".")
            self.run_git(root, "commit", "-m", "product change after skillpack")
        return base, introduction

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

    def test_historical_scope_uses_introduction_parent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_history_fixture(root)
            result = MODULE.validate(root)
        self.assertEqual(result["status"], "success", result["errors"])

    def test_historical_scope_rejects_product_change_in_introduction(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.build_history_fixture(root, out_of_scope_introduction=True)
            result = MODULE.validate(root)
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "skillpack introduction out-of-scope change: moneysweep/introduced_with_skillpack.py",
            result["errors"],
        )

    def test_current_scope_is_independent_of_historical_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, introduction = self.build_history_fixture(
                root, post_introduction_product_change=False
            )
            workflow = root / ".github/workflows/unified-skillpack-conformance.yml"
            workflow.write_text("name: fixture\n# allowed repair\n", encoding="utf-8")
            self.run_git(root, "add", ".")
            self.run_git(root, "commit", "-m", "allowed validator repair")
            result = MODULE.validate(root, enforce_change_scope=True, change_base=introduction)
        self.assertEqual(result["status"], "success", result["errors"])

    def test_current_scope_rejects_product_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            _, introduction = self.build_history_fixture(root)
            result = MODULE.validate(root, enforce_change_scope=True, change_base=introduction)
        self.assertEqual(result["status"], "failed")
        self.assertIn(
            "current change scope out-of-scope change: moneysweep/product_after.py",
            result["errors"],
        )

    def test_shallow_history_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            self.build_history_fixture(source)
            clone = Path(directory) / "clone"
            subprocess.run(
                ["git", "clone", "--depth", "1", source.as_uri(), str(clone)],
                check=True,
                capture_output=True,
                text=True,
            )
            result = MODULE.validate(clone)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(
            any(
                error.startswith("pinned base commit object is unavailable:")
                for error in result["errors"]
            ),
            result["errors"],
        )


if __name__ == "__main__":
    unittest.main()
