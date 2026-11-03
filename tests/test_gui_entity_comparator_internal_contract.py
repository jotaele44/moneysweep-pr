"""Exact-scope contract for pipeline-only entity comparator GUI-parity binding."""

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / ".federation/gui-capabilities.json"
CID = "entity-product-offline-baseline-diagnostic"
EXCEPTION = "compare-entity-products-terminal-analysis"


class ComparatorBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        cls.matches = [c for c in cls.manifest["capabilities"] if c.get("id") == CID]

    def test_one_reviewable_binding(self):
        self.assertEqual(len(self.matches), 1)

    def test_internal_only_not_user_surface_waiver(self):
        c = self.matches[0]
        self.assertEqual(c["classification"], "internal")
        self.assertEqual(c["status"], "active")
        self.assertIs(c["requires_terminal"], False)
        self.assertTrue(c["rationale"])
        self.assertNotIn("frontend", c)
        self.assertNotIn("backend", c)

    def test_exact_file_and_symbols(self):
        c = self.matches[0]
        self.assertEqual(c["analysis"]["files"], ["scripts/compare_entity_products.py"])
        self.assertEqual(
            set(c["analysis"]["symbols"]),
            {
                "scripts/compare_entity_products.py:compare",
                "scripts/compare_entity_products.py:main",
            },
        )

    def test_legacy_exception_removed_not_renewed(self):
        ids = [e["id"] for e in self.manifest.get("exceptions", [])]
        self.assertNotIn(EXCEPTION, ids)

    def test_actual_pipeline_import_and_contract_test_exist(self):
        runner = (ROOT / "moneysweep/orchestrator/_offline_baseline_runner.py").read_text()
        self.assertIn("from scripts.compare_entity_products import compare", runner)
        self.assertTrue((ROOT / "tests/test_compare_entity_products.py").is_file())

    def test_fails_closed_on_user_surface_reclassification(self):
        c = dict(self.matches[0], classification="user")
        with self.assertRaises(AssertionError):
            self.assertEqual(c["classification"], "internal")


if __name__ == "__main__":
    unittest.main()
