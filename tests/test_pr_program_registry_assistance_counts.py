"""Offline fail-closed regressions for the PR assistance count contract."""
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "research/pr_program_registry/acquire_assistance_class_counts.py"
)
spec = importlib.util.spec_from_file_location("pr_assistance_counts", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def valid_response(changes=None):
    values = {
        "grants": 2,
        "loans": 1,
        "direct_payments": 4,
        "other": 3,
        "contracts": 0,
        "idvs": 0,
    }
    values.update(changes or {})
    return json.dumps({"spending_level": "awards", "results": values}).encode()


class AssistanceCountTests(unittest.TestCase):
    def test_exact_ten_queries(self):
        self.assertEqual(len(module.YEARS) * len(module.LOCATIONS), 10)

    def test_geographies_not_conflated(self):
        a = json.loads(module.request_bytes(2026, "recipient_pr"))
        b = json.loads(module.request_bytes(2026, "performance_pr"))
        self.assertNotEqual(a, b)
        self.assertNotIn("place_of_performance_locations", a["filters"])
        self.assertNotIn("recipient_locations", b["filters"])

    def test_fy_boundary(self):
        a = json.loads(module.request_bytes(2022, "recipient_pr"))
        self.assertEqual(a["filters"]["time_period"], [
            {"start_date": "2021-10-01", "end_date": "2022-09-30"}
        ])

    def test_filter_only_public_documented_codes(self):
        a = json.loads(module.request_bytes(2026, "recipient_pr"))
        self.assertEqual(a["filters"]["award_type_codes"], list(module.CODES))
        self.assertNotIn("-1", a["filters"]["award_type_codes"])

    def test_unknown_scope_rejected(self):
        with self.assertRaisesRegex(ValueError, "OUT_OF_SCOPE_QUERY"):
            module.request_bytes(2020, "recipient_pr")

    def test_conservation(self):
        self.assertEqual(sum(module.parse_count(valid_response()).values()), 10)

    def test_zero_valid(self):
        self.assertEqual(sum(module.parse_count(valid_response({
            name: 0 for name in module.GROUPS
        })).values()), 0)

    def test_negative_denied(self):
        with self.assertRaisesRegex(ValueError, "INVALID_COUNT_loans"):
            module.parse_count(valid_response({"loans": -1}))

    def test_boolean_denied(self):
        with self.assertRaisesRegex(ValueError, "INVALID_COUNT_other"):
            module.parse_count(valid_response({"other": True}))

    def test_contract_leakage_denied(self):
        with self.assertRaisesRegex(ValueError, "NON_ASSISTANCE_LEAKAGE_contracts"):
            module.parse_count(valid_response({"contracts": 1}))

    def test_wrong_level_denied(self):
        with self.assertRaisesRegex(ValueError, "INVALID_SPENDING_LEVEL"):
            module.parse_count(b'{"spending_level":"subawards","results":{}}')

    def test_missing_results_denied(self):
        with self.assertRaisesRegex(ValueError, "MISSING_COUNT_RESULTS"):
            module.parse_count(b'{"spending_level":"awards"}')


if __name__ == "__main__":
    unittest.main()
