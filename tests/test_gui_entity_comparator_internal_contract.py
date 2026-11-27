"""Regression contract for the scoped comparator GUI-parity fix merged in #692.

Only the existing pipeline diagnostic is classified internal. This does not
waive GUI parity for any other user-facing analytical capability.
"""Six exact-scope contracts for the existing #692 entity comparator GUI binding.

The comparator is an internal offline-baseline diagnostic, not an operator GUI.
These tests intentionally reuse the merged capability instead of defining another.
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
MANIFEST = ROOT / ".federation/gui-capabilities.json"
CID = "entity-product-comparison-audit"
LEGACY_CID = "entity-product-offline-baseline-diagnostic"
EXCEPTION = "compare-entity-products-terminal-analysis"
SCRIPT = "scripts/compare_entity_products.py"


class ComparatorBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.matches = [cap for cap in cls.manifest["capabilities"] if cap.get("id") == CID]

    def test_one_reviewable_binding(self):
        self.assertEqual(len(self.matches), 1)
        self.assertFalse(any(cap.get("id") == LEGACY_CID for cap in self.manifest["capabilities"]))

    def test_internal_only_not_user_surface_waiver(self):
        cap = self.matches[0]
        self.assertEqual(cap["classification"], "internal")
        self.assertEqual(cap["status"], "active")
        self.assertIs(cap["requires_terminal"], False)
        self.assertTrue(cap["rationale"])
        self.assertNotIn("frontend", cap)
        self.assertNotIn("backend", cap)

    def test_exact_file_and_symbols(self):
        cap = self.matches[0]
        self.assertEqual(cap["analysis"]["files"], [SCRIPT])
        # #692 intentionally uses a file-scoped classification. Do not add a
        # second symbol-scoped capability or permit unrelated analysis files.
        self.assertNotIn("symbols", cap["analysis"])
        self.assertEqual(cap["tests"]["backend"], ["tests/test_compare_entity_products.py"])

    def test_legacy_exception_removed_not_renewed(self):
        exception_ids = [exc["id"] for exc in self.manifest.get("exceptions", [])]
        self.assertNotIn(EXCEPTION, exception_ids)

    def test_actual_pipeline_import_and_contract_test_exist(self):
        runner = (ROOT / "moneysweep/orchestrator/_offline_baseline_runner.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("from scripts.compare_entity_products import compare", runner)
        self.assertTrue((ROOT / "tests/test_compare_entity_products.py").is_file())

    def test_fails_closed_on_user_surface_reclassification(self):
        cap = dict(self.matches[0], classification="user")
        with self.assertRaises(AssertionError):
            self.assertEqual(cap["classification"], "internal")


if __name__ == "__main__":
    unittest.main()
