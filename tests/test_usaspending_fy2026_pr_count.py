"""Offline positive/adversarial USAspending PR FY2026 count contract."""
import importlib.util
import json
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "scripts/probe_usaspending_fy2026_pr_count.py"
spec = importlib.util.spec_from_file_location("pr_count", SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class CountContractTests(unittest.TestCase):
    def test_two_geographies_stay_separate(self):
        recipient = json.loads(module.request_bytes("recipient_pr"))
        performance = json.loads(module.request_bytes("performance_pr"))
        self.assertEqual(recipient["filters"]["recipient_locations"][0]["state"], "PR")
        self.assertEqual(performance["filters"]["place_of_performance_locations"][0]["state"], "PR")
        self.assertNotIn("place_of_performance_locations", recipient["filters"])
        self.assertNotIn("recipient_locations", performance["filters"])

    def test_grant_codes_and_time_window(self):
        a = json.loads(module.request_bytes("recipient_pr"))
        self.assertEqual(a["filters"]["award_type_codes"], ["02", "03", "04", "05"])
        self.assertEqual(a["filters"]["time_period"], [module.PERIOD])
        self.assertFalse(a["subawards"])

    def test_unexpected_scope_denied(self):
        with self.assertRaisesRegex(ValueError, "UNKNOWN_LOCATION_SCOPE"):
            module.request_bytes("outside_pr")

    def test_zero_is_not_source_failure(self):
        self.assertEqual(module.parse_count(b'{"spending_level":"awards","results":{"grants":0}}'), 0)

    def test_valid_integer(self):
        self.assertEqual(module.parse_count(b'{"spending_level":"awards","results":{"grants":251}}'), 251)

    def test_missing_grant_count_denied(self):
        with self.assertRaisesRegex(ValueError, "GRANT_COUNT_INVALID"):
            module.parse_count(b'{"spending_level":"awards","results":{}}')

    def test_boolean_denied(self):
        with self.assertRaisesRegex(ValueError, "GRANT_COUNT_INVALID"):
            module.parse_count(b'{"spending_level":"awards","results":{"grants":true}}')

    def test_negative_denied(self):
        with self.assertRaisesRegex(ValueError, "GRANT_COUNT_INVALID"):
            module.parse_count(b'{"spending_level":"awards","results":{"grants":-1}}')

    def test_wrong_level_denied(self):
        with self.assertRaisesRegex(ValueError, "WRONG_SPENDING_LEVEL"):
            module.parse_count(b'{"spending_level":"subawards","results":{"grants":9}}')


if __name__ == "__main__":
    unittest.main()
