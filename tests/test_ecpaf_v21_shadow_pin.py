"""Negative, source-identity and fail-closed tests for ECPAF's MoneySweep pilot."""

import copy
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "ecpaf_shadow_pin", ROOT / "scripts/check_ecpaf_v21_shadow_pin.py"
)
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


class ShadowPinTests(unittest.TestCase):
    def setUp(self):
        self.pin = json.loads(checker.PIN_PATH.read_text())
        self.head = "a" * 40
        self.pin["authority_commit"] = self.head
        self.policy = {
            "schema_version": "ecpaf-policy/2.1",
            "policy_id": "ECPAF-V2.1",
            "policy_revision": "2.1.1",
            "authority": "jotaele44/thehub-pr",
            "mode": "SHADOW_PILOT",
            "independent_review_requirement": "NOT_REQUIRED",
            "advisory_review_scored": False,
            "protected_release_behavior": "UNCHANGED",
            "certification": "WITHHELD",
            "core_repositories": ["jotaele44/moneysweep-pr"],
            "semantics": {"pilot_can_authorize_operations": False},
        }
        self.bind()

    def bind(self):
        self.raw = (json.dumps(self.policy, sort_keys=True) + "\n").encode()
        self.pin["authority_policy_sha256"] = hashlib.sha256(self.raw).hexdigest()

    def validate(self):
        return checker.validate_binding(self.pin, self.raw, self.head)

    def test_valid_binding_is_shadow_only(self):
        result = self.validate()
        self.assertEqual(result["state"], "PASS")
        self.assertFalse(result["release_authorized"])
        self.assertEqual(result["certification"], "WITHHELD")

    def test_wrong_authority_commit(self):
        self.head = "b" * 40
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_malformed_commit_or_digest(self):
        for key in ["authority_commit", "authority_policy_sha256"]:
            before = self.pin[key]
            self.pin[key] = "main"
            with self.assertRaises(checker.PinError):
                self.validate()
            self.pin[key] = before

    def test_mutated_authority_bytes(self):
        self.raw += b" "
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_no_release_authorization(self):
        for key, value in [
            ("release_authorized", True),
            ("protected_operations_authorized", ["merge"]),
            ("certification", "CERTIFIED"),
            ("read_only", False),
            ("mode", "ENFORCE_RELEASE"),
        ]:
            previous = copy.deepcopy(self.pin[key])
            self.pin[key] = value
            with self.assertRaises(checker.PinError):
                self.validate()
            self.pin[key] = previous

    def test_identity_and_scope_cannot_change(self):
        for key in [
            "consumer_repository",
            "authority_repository",
            "authority_policy_revision",
            "authority_policy_path",
        ]:
            value = self.pin[key]
            self.pin[key] = "spoofed"
            with self.assertRaises(checker.PinError):
                self.validate()
            self.pin[key] = value

    def test_missing_or_extra_field(self):
        removed = self.pin.pop("read_only")
        with self.assertRaises(checker.PinError):
            self.validate()
        self.pin["read_only"] = removed
        self.pin["unclassified"] = "PASS"
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_duplicate_keys_disallowed(self):
        with self.assertRaises(checker.PinError):
            checker.load_object(b'{"state":"PASS","state":"FAIL"}')

    def test_nonfinite_json_disallowed(self):
        with self.assertRaises(checker.PinError):
            checker.load_object(b'{"value":NaN}')

    def test_owner_policy_review_requirement(self):
        self.policy["independent_review_requirement"] = "REQUIRED"
        self.bind()
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_advisory_review_cannot_be_scored(self):
        self.policy["advisory_review_scored"] = True
        self.bind()
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_moneysweep_must_be_in_authority_scope(self):
        self.policy["core_repositories"] = []
        self.bind()
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_unsafe_authority_semantics_fail_closed(self):
        self.policy["semantics"]["pilot_can_authorize_operations"] = True
        self.bind()
        with self.assertRaises(checker.PinError):
            self.validate()

    def test_source_is_exact_committed_file_not_mutable_worktree(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            authority = temp / "thehub"
            authority.mkdir()
            subprocess.run(["git", "init", "-q", str(authority)], check=True)
            subprocess.run(
                ["git", "-C", str(authority), "config", "user.name", "Fixture"], check=True
            )
            subprocess.run(
                ["git", "-C", str(authority), "config", "user.email", "fixture@example.invalid"],
                check=True,
            )
            policy_path = authority / checker.AUTHORITY_PATH
            policy_path.parent.mkdir(parents=True)
            policy_path.write_bytes(self.raw)
            subprocess.run(["git", "-C", str(authority), "add", checker.AUTHORITY_PATH], check=True)
            subprocess.run(
                ["git", "-C", str(authority), "commit", "-q", "-m", "fixture"], check=True
            )
            head = subprocess.check_output(
                ["git", "-C", str(authority), "rev-parse", "HEAD"], text=True
            ).strip()
            self.pin["authority_commit"] = head
            pin_file = temp / "pin.json"
            pin_file.write_text(json.dumps(self.pin))
            self.assertEqual(checker.validate_checkout(pin_file, authority)["state"], "PASS")
            policy_path.write_bytes(self.raw + b"tamper")
            with self.assertRaises(checker.PinError):
                checker.validate_checkout(pin_file, authority)

    def test_symlink_pin_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            regular = temp / "regular.json"
            regular.write_text(json.dumps(self.pin))
            link = temp / "link.json"
            link.symlink_to(regular)
            with self.assertRaises(checker.PinError):
                checker.validate_checkout(link, temp)


if __name__ == "__main__":
    unittest.main()
