#!/usr/bin/env python3
"""Validate the repository-local HAF federation contract fail closed."""

from __future__ import annotations

import json
import os
import shlex
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = Path(".federation/haf_contract.json")
EXPECTED = {
    "schema_version": "haf_repo_contract_v2",
    "haf_contract_version": "2.0.0",
    "framework_compatibility": ">=0.4.0,<1.0.0",
    "program_id": "moneysweep-pr",
    "federation_role": "public_money_intelligence_node",
    "certification_required": True,
    "raw_snapshot_policy": "PRESERVE_OR_IMMUTABLE_REFERENCE",
    "identity_policy": "EVIDENCE_PRIORITY_FAIL_CLOSED",
    "unresolved_policy": "FAIL_CLOSED",
    "canonical_export_required": True,
    "adapter_state": "COMPATIBLE_PENDING_CI",
    "native_contract": "federation.json",
}
COMMAND_BINDINGS = {
    "native_test_command": "test_suite",
    "canonical_export_command": "export_canonical",
}


def validate(root: Path, repository: str) -> list[str]:
    path = root / CONTRACT
    if not path.is_file():
        return [f"missing HAF contract: {CONTRACT}"]
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return [f"invalid HAF contract: {exc}"]
    if not isinstance(contract, dict):
        return ["HAF contract root must be an object"]

    errors = [
        f"{key}: expected {expected!r}, got {contract.get(key)!r}"
        for key, expected in EXPECTED.items()
        if contract.get(key) != expected
    ]
    if contract.get("repository_full_name") != repository:
        errors.append("repository_full_name does not match GITHUB_REPOSITORY")

    native_path = root / str(contract.get("native_contract", ""))
    if not native_path.is_file():
        errors.append("native_contract does not resolve to a file")
    else:
        try:
            native = json.loads(native_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            errors.append(f"invalid native contract: {exc}")
        else:
            if not isinstance(native, dict):
                errors.append("native contract root must be an object")
            else:
                for key in ("program_id", "repository_full_name", "federation_role"):
                    if native.get(key) != contract.get(key):
                        errors.append(f"native contract {key} does not match HAF contract")

                commands = native.get("hub_callable_commands")
                if not isinstance(commands, dict):
                    errors.append("native contract hub_callable_commands must be an object")
                else:
                    for contract_key, native_key in COMMAND_BINDINGS.items():
                        if contract.get(contract_key) != commands.get(native_key):
                            errors.append(
                                f"{contract_key} does not match native contract "
                                f"hub_callable_commands.{native_key}"
                            )

    for key in COMMAND_BINDINGS:
        command = contract.get(key)
        if not isinstance(command, str) or not command.strip():
            errors.append(f"{key} must be a non-empty command")
            continue
        try:
            parts = shlex.split(command)
        except ValueError as exc:
            errors.append(f"{key} is malformed: {exc}")
            continue
        for part in (item for item in parts if item.endswith(".py")):
            script_path = Path(part)
            if script_path.is_absolute() or ".." in script_path.parts:
                errors.append(f"{key} references a script outside the repository")
            elif not (root / script_path).is_file():
                errors.append(f"{key} references a missing script")
    return errors


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    if not repository:
        print("HAF_CONTRACT_FAIL: GITHUB_REPOSITORY is required")
        return 1
    errors = validate(ROOT, repository)
    if errors:
        for error in errors:
            print(f"HAF_CONTRACT_FAIL: {error}")
        return 1
    print("HAF_CONTRACT_PASS: moneysweep-pr")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
