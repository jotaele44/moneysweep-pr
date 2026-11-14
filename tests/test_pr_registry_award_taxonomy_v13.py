"""Negative and positive tests for USAspending legacy/expanded taxonomy."""

import importlib.util
import json
import unittest
from pathlib import Path

p = (
    Path(__file__).resolve().parents[1]
    / "research/pr_program_registry/compare_award_type_taxonomies.py"
)
spec = importlib.util.spec_from_file_location("taxonomy", p)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def response(n=5):
    return json.dumps(
        {
            "spending_level": "awards",
            "results": {
                "grants": n,
                "loans": 1,
                "direct_payments": 2,
                "other": 3,
                "contracts": 0,
                "idvs": 0,
            },
        }
    ).encode()


class TaxonomyTest(unittest.TestCase):
    def test_all_years_and_geographies(self):
        self.assertEqual((len(m.YEARS), len(m.GEOGRAPHIES)), (5, 2))

    def test_complete_raw_type_set(self):
        self.assertEqual(len(m.LEGACY), 10)
        self.assertEqual(len(m.NEW), 10)
        self.assertEqual(len(set(m.MODES["expanded"])), 20)

    def test_all_new_codes_preserved(self):
        self.assertEqual(m.NEW, tuple(f"F{i:03d}" for i in range(1, 11)))

    def test_geographies_not_collapsed(self):
        a = json.loads(m.encode_body(2026, "recipient_pr", "expanded"))
        b = json.loads(m.encode_body(2026, "performance_pr", "expanded"))
        self.assertNotEqual(a, b)
        self.assertNotIn("recipient_locations", b["filters"])
        self.assertNotIn("place_of_performance_locations", a["filters"])

    def test_legacy_is_exact_predecessor(self):
        a = json.loads(m.encode_body(2026, "recipient_pr", "legacy_only"))
        self.assertEqual(a["filters"]["award_type_codes"], list(m.LEGACY))
        self.assertEqual(
            a["filters"]["time_period"], [{"start_date": "2025-10-01", "end_date": "2026-09-30"}]
        )

    def test_invalid_scope_denied(self):
        for fy, geo, mode in [
            (2027, "recipient_pr", "expanded"),
            (2026, "outside", "expanded"),
            (2026, "recipient_pr", "unknown"),
        ]:
            with self.assertRaises(ValueError):
                m.encode_body(fy, geo, mode)

    def test_valid_result(self):
        self.assertEqual(m.validate_count(response())["grants"], 5)

    def test_boolean_not_integer(self):
        data = json.loads(response())
        data["results"]["grants"] = True
        with self.assertRaisesRegex(ValueError, "INVALID_COUNT_grants"):
            m.validate_count(json.dumps(data).encode())

    def test_missing_results_denied(self):
        with self.assertRaisesRegex(ValueError, "COUNT_RESULTS_MISSING"):
            m.validate_count(b'{"spending_level":"awards"}')

    def test_wrong_level_denied(self):
        with self.assertRaisesRegex(ValueError, "INVALID_COUNT_SPENDING_LEVEL"):
            m.validate_count(b'{"spending_level":"subawards","results":{}}')

    def test_procurement_leak_denied(self):
        d = json.loads(response())
        d["results"]["contracts"] = 1
        with self.assertRaisesRegex(ValueError, "PROCUREMENT_CROSSCONTAMINATION"):
            m.validate_count(json.dumps(d).encode())

    def test_negative_expansion_denied(self):
        v = m.validate_count(response())
        reduced = dict(v)
        reduced["grants"] -= 1
        with self.assertRaisesRegex(ValueError, "EXPANDED_SCOPE_SMALLER"):
            m.compare(v, reduced)

    def test_delta_is_not_program_identity(self):
        a = m.validate_count(response(5))
        b = m.validate_count(response(8))
        x = m.compare(a, b)
        self.assertEqual(x["expanded_minus_legacy"]["grants"], 3)
        self.assertEqual(x["candidate_identity_promotions"], 0)


if __name__ == "__main__":
    unittest.main()
