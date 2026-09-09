#!/usr/bin/env python3
"""Validate MoneySweep runtime, development, and Hub setup profiles."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_INPUT = "requirements.in"
RUNTIME_REQUIREMENTS = "requirements.txt"
RUNTIME_LOCK = "requirements.lock"
DEV_REQUIREMENTS = "requirements-dev.txt"
FEDERATION_MANIFEST = "federation.json"
TEST_ONLY = {"pytest", "pytest-cov"}
_REQUIREMENT_NAME = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


class DependencyPlaneError(RuntimeError):
    """Raised when dependency ownership, conservation, or profile binding fails."""


def _read(path: Path) -> str:
    if not path.is_file():
        raise DependencyPlaneError(f"required dependency file is missing: {path.name}")
    return path.read_text(encoding="utf-8")


def _logical_lines(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _names(lines: Iterable[str]) -> set[str]:
    names: set[str] = set()
    for line in lines:
        if line.startswith(("-r ", "--requirement ", "-c ", "--constraint ")):
            continue
        match = _REQUIREMENT_NAME.match(line)
        if not match:
            raise DependencyPlaneError(f"unrecognized requirement record: {line!r}")
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def _commands(root: Path) -> dict[str, str]:
    try:
        manifest = json.loads(_read(root / FEDERATION_MANIFEST))
    except json.JSONDecodeError as exc:
        raise DependencyPlaneError(f"federation.json is not valid JSON: {exc}") from exc
    commands = manifest.get("hub_callable_commands")
    if not isinstance(commands, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in commands.items()
    ):
        raise DependencyPlaneError("federation.json hub_callable_commands must be string pairs")
    return commands


def validate(root: Path = REPO_ROOT) -> dict[str, object]:
    runtime_input_text = _read(root / RUNTIME_INPUT)
    runtime_requirements_text = _read(root / RUNTIME_REQUIREMENTS)
    if runtime_input_text != runtime_requirements_text:
        raise DependencyPlaneError(
            "requirements.in and requirements.txt must remain byte-identical runtime manifests"
        )

    runtime_direct = _names(_logical_lines(runtime_input_text))
    runtime_locked = _names(_logical_lines(_read(root / RUNTIME_LOCK)))
    dev_lines = _logical_lines(_read(root / DEV_REQUIREMENTS))
    dev_direct = _names(dev_lines)

    if not any(
        line in {"-r requirements.txt", "--requirement requirements.txt"} for line in dev_lines
    ):
        raise DependencyPlaneError("development requirements must include requirements.txt")

    leaked_direct = sorted(runtime_direct & TEST_ONLY)
    leaked_locked = sorted(runtime_locked & TEST_ONLY)
    if leaked_direct or leaked_locked:
        raise DependencyPlaneError(
            f"test tooling leaked into runtime plane: direct={leaked_direct} locked={leaked_locked}"
        )
    missing_test_tools = sorted(TEST_ONLY - dev_direct)
    if missing_test_tools:
        raise DependencyPlaneError(
            f"development requirements omit test tools: {missing_test_tools}"
        )
    missing_runtime_locks = sorted(runtime_direct - runtime_locked)
    if missing_runtime_locks:
        raise DependencyPlaneError(
            f"runtime direct requirements missing from runtime lock: {missing_runtime_locks}"
        )

    commands = _commands(root)
    setup = commands.get("setup", "")
    runtime_setup = commands.get("runtime_setup", "")
    test_suite = commands.get("test_suite", "")
    if DEV_REQUIREMENTS not in setup:
        raise DependencyPlaneError(
            f"Hub setup must prepare the audit/test profile with {DEV_REQUIREMENTS}"
        )
    if RUNTIME_REQUIREMENTS not in runtime_setup or DEV_REQUIREMENTS in runtime_setup:
        raise DependencyPlaneError(f"Hub runtime_setup must install only {RUNTIME_REQUIREMENTS}")
    if "pytest" not in test_suite:
        raise DependencyPlaneError("Hub test_suite must execute the declared test runner")

    return {
        "status": "PASS",
        "runtime_manifests_byte_identical": True,
        "runtime_direct_count": len(runtime_direct),
        "runtime_locked_count": len(runtime_locked),
        "development_direct_count": len(dev_direct),
        "test_packages_in_runtime": 0,
        "hub_setup_profile_bound": True,
        "hub_runtime_profile_bound": True,
    }


def main() -> int:
    try:
        summary = validate()
    except DependencyPlaneError as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 1
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
