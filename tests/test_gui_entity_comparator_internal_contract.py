"""Regression contract for the scoped comparator GUI-parity fix merged in #692.

Only the existing pipeline diagnostic is classified internal. This does not
waive GUI parity for any other user-facing analytical capability.
"""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".federation" / "gui-capabilities.json"
CAPABILITY = "entity-product-comparison-audit"
OLD_EXCEPTION = "compare-entity-products-terminal-analysis"
SCRIPT = "scripts/compare_entity_products.py"


class ComparatorGuiParityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.bindings = [
            item
            for item in cls.manifest["capabilities"]
            if item.get("id") == CAPABILITY
        ]

    def test_single_exact_capability(self) -> None:
        self.assertEqual(len(self.bindings), 1)

    def test_is_internal_pipeline_only(self) -> None:
        binding = self.bindings[0]
        self.assertEqual(binding["classification"], "internal")
        self.assertEqual(binding["status"], "active")
        self.assertIs(binding["requires_terminal"], False)
        self.assertTrue(binding["rationale"])
        self.assertNotIn("frontend", binding)
        self.assertNotIn("backend", binding)

    def test_scope_is_one_comparator_script(self) -> None:
        binding = self.bindings[0]
        self.assertEqual(binding["analysis"]["files"], [SCRIPT])
        self.assertEqual(
            binding["tests"]["backend"],
            ["tests/test_compare_entity_products.py"],
        )

    def test_no_duplicate_comparator_capabilities(self) -> None:
        other = [
            item["id"]
            for item in self.manifest["capabilities"]
            if item.get("id") != CAPABILITY
            and SCRIPT in item.get("analysis", {}).get("files", [])
        ]
        self.assertEqual(other, [])

    def test_expired_exception_is_removed(self) -> None:
        ids = [item["id"] for item in self.manifest.get("exceptions", [])]
        self.assertNotIn(OLD_EXCEPTION, ids)

    def test_pipeline_binding_and_diagnostic_test_exist(self) -> None:
        runner = (
            ROOT / "moneysweep" / "orchestrator" / "_offline_baseline_runner.py"
        ).read_text(encoding="utf-8")
        self.assertIn("from scripts.compare_entity_products import compare", runner)
        self.assertTrue((ROOT / "tests" / "test_compare_entity_products.py").is_file())


if __name__ == "__main__":
    unittest.main()
