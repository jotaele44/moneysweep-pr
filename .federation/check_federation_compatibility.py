#!/usr/bin/env python3
"""Validate the frozen federation compatibility receipt and changed-path scope."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

RECEIPT_PATH = "governance/federation_compatibility.json"
SCHEMA_VERSION = "prii_repo_compatibility_receipt_v1"
ALLOWED_DISPOSITIONS = {"UNAFFECTED", "COMPATIBLE", "UPDATED", "BLOCKED"}
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def validate_receipt(receipt: dict[str, Any], expected_repo: str) -> list[str]:
    errors: list[str] = []
    if receipt.get("schema_version") != SCHEMA_VERSION:
        errors.append("unknown compatibility receipt schema")
    if receipt.get("repo") != expected_repo:
        errors.append("wrong repo in compatibility receipt")
    disposition = receipt.get("disposition")
    if disposition not in ALLOWED_DISPOSITIONS:
        errors.append("unknown compatibility disposition")
    elif disposition == "BLOCKED":
        errors.append("federation compatibility is BLOCKED")

    if receipt.get("central_governance_repo") != "jotaele44/thehub-pr":
        errors.append("wrong central governance repository")
    if receipt.get("central_governance_pr") != 218:
        errors.append("wrong central governance PR")
    if receipt.get("central_governance_url") != "https://github.com/jotaele44/thehub-pr/pull/218":
        errors.append("wrong central governance URL")
    for field in ("central_governance_head_sha", "central_governance_merge_sha"):
        if not SHA_PATTERN.fullmatch(str(receipt.get(field) or "")):
            errors.append(f"invalid {field}")
    if receipt.get("central_governance_merged_at") != "2026-09-01T00:10:41Z":
        errors.append("wrong central governance merge timestamp")

    contracts = receipt.get("contracts")
    if not isinstance(contracts, list) or not contracts or len(contracts) != len(set(contracts)):
        errors.append("contracts must be a non-empty unique list")
    watched = receipt.get("watched_paths")
    if not isinstance(watched, list) or not watched or len(watched) != len(set(watched)):
        errors.append("watched_paths must be a non-empty unique list")
    elif not all(isinstance(path, str) and path and not path.startswith("/") for path in watched):
        errors.append("watched_paths must contain repository-relative paths")
    return errors


def validate_change_scope(changed: set[str], watched: set[str]) -> list[str]:
    if changed.intersection(watched) and RECEIPT_PATH not in changed:
        return ["federation contract surface changed without compatibility receipt update"]
    return []


def changed_paths(base: str, head: str) -> set[str]:
    if not base or not head or set(base) == {"0"}:
        raise ValueError("missing authoritative event commit range")
    output = subprocess.check_output(["git", "diff", "--name-only", f"{base}..{head}"], text=True)
    return set(output.splitlines())


def main() -> int:
    receipt = json.loads(Path(RECEIPT_PATH).read_text(encoding="utf-8"))
    errors = validate_receipt(receipt, os.environ.get("EXPECTED_REPO", ""))
    try:
        changed = changed_paths(os.environ.get("BASE_SHA", ""), os.environ.get("HEAD_SHA", ""))
    except (ValueError, subprocess.CalledProcessError) as exc:
        errors.append(str(exc))
        changed = set()
    errors.extend(validate_change_scope(changed, set(receipt.get("watched_paths") or [])))
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("FEDERATION_COMPATIBILITY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
