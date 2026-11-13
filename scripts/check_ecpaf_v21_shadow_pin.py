#!/usr/bin/env python3
"""Check MoneySweep's read-only pin to TheHub's immutable ECPAF policy.

This checker neither calculates federation readiness nor grants release authority.
TheHub remains the sole cross-repository governance authority; this is a
consumer identity/byte-binding check, not a second policy implementation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_PATH = REPO_ROOT / "federation/ecpaf_v21_shadow_policy.pin.json"
EXPECTED_FIELDS = {
    "schema_version",
    "consumer_repository",
    "authority_repository",
    "authority_commit",
    "authority_policy_path",
    "authority_policy_sha256",
    "authority_policy_revision",
    "mode",
    "read_only",
    "protected_operations_authorized",
    "release_authorized",
    "certification",
}
AUTHORITY_PATH = "governance/ecpaf/v2.1/policy.json"


class PinError(ValueError):
    """Invalid or unverifiable policy binding."""


def load_object(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise PinError("duplicate JSON key: " + key)
            result[key] = value
        return result

    def nonfinite(value):
        raise PinError("nonfinite JSON constant: " + value)

    obj = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    if not isinstance(obj, dict):
        raise PinError("expected JSON object")
    return obj


def validate_binding(pin: dict, policy_bytes: bytes, observed_head: str) -> dict:
    if set(pin) != EXPECTED_FIELDS:
        raise PinError("unexpected or missing pin fields")
    expected = {
        "schema_version": "ecpaf-v2.1-shadow-consumer-pin/1",
        "consumer_repository": "jotaele44/moneysweep-pr",
        "authority_repository": "jotaele44/thehub-pr",
        "authority_policy_path": AUTHORITY_PATH,
        "authority_policy_revision": "2.1.1",
        "mode": "SHADOW_ONLY",
        "read_only": True,
        "protected_operations_authorized": [],
        "release_authorized": False,
        "certification": "WITHHELD",
    }
    for key, value in expected.items():
        if type(pin[key]) is not type(value) or pin[key] != value:
            raise PinError("invalid pin declaration: " + key)
    sha = pin["authority_commit"]
    digest = pin["authority_policy_sha256"]
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise PinError("authority commit must be exact SHA")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise PinError("authority policy hash must be SHA-256")
    if sha != observed_head:
        raise PinError("authority HEAD differs from pin")
    if hashlib.sha256(policy_bytes).hexdigest() != digest:
        raise PinError("authority policy bytes differ from pin")
    policy = load_object(policy_bytes)
    conditions = {
        "schema_version": "ecpaf-policy/2.1",
        "policy_id": "ECPAF-V2.1",
        "policy_revision": "2.1.1",
        "authority": "jotaele44/thehub-pr",
        "mode": "SHADOW_PILOT",
        "independent_review_requirement": "NOT_REQUIRED",
        "advisory_review_scored": False,
        "protected_release_behavior": "UNCHANGED",
        "certification": "WITHHELD",
    }
    for key, value in conditions.items():
        if type(policy.get(key)) is not type(value) or policy.get(key) != value:
            raise PinError("unacceptable authority policy: " + key)
    if "jotaele44/moneysweep-pr" not in policy.get("core_repositories", []):
        raise PinError("consumer is not declared in core scope")
    if any(value is not False for value in policy.get("semantics", {}).values()):
        raise PinError("unsafe authority semantics")
    return {
        "state": "PASS",
        "consumer_repository": pin["consumer_repository"],
        "authority_commit": sha,
        "policy_sha256": digest,
        "policy_revision": "2.1.1",
        "mode": "SHADOW_ONLY",
        "release_authorized": False,
        "certification": "WITHHELD",
    }


def validate_checkout(pin_path: Path, authority_root: Path) -> dict:
    if pin_path.is_symlink() or not pin_path.is_file():
        raise PinError("pin must be an ordinary file")
    if authority_root.is_symlink() or not authority_root.is_dir():
        raise PinError("authority checkout unavailable")
    policy_file = authority_root / AUTHORITY_PATH
    if policy_file.is_symlink() or not policy_file.is_file():
        raise PinError("authority policy file unavailable")
    head = subprocess.run(
        ["git", "-C", str(authority_root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    policy_git_bytes = subprocess.run(
        ["git", "-C", str(authority_root), "show", "HEAD:" + AUTHORITY_PATH],
        capture_output=True,
        check=True,
    ).stdout
    policy_file_bytes = policy_file.read_bytes()
    if policy_git_bytes != policy_file_bytes:
        raise PinError("authority checkout policy differs from git object")
    return validate_binding(load_object(pin_path.read_bytes()), policy_git_bytes, head)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, default=PIN_PATH)
    parser.add_argument("--authority-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate_checkout(args.pin, args.authority_root)
    except (
        PinError,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ) as exc:
        print(
            json.dumps(
                {
                    "state": "FAIL_CLOSED",
                    "error": str(exc),
                    "release_authorized": False,
                    "certification": "WITHHELD",
                }
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
