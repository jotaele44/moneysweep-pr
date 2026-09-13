#!/usr/bin/env python3
"""Fail closed if this operational repository gains federation-admin authority."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "moneysweep-pr"
FORBIDDEN = (
    "AdminKit",
    "federation-admin-workstation",
    "lockstep.override",
    "certification.issue",
    "deployment.promote",
    "PRII_MANAGER_BOOTSTRAP_NONCE",
)
SOURCE_SUFFIXES = {
    ".go",
    ".java",
    ".js",
    ".jsx",
    ".kt",
    ".py",
    ".rs",
    ".swift",
    ".ts",
    ".tsx",
    ".yaml",
    ".yml",
}


def fail(message: str) -> None:
    print("ADMIN_BOUNDARY_FAIL: " + message, file=sys.stderr)
    raise SystemExit(1)


manifest = json.loads((ROOT / ".federation/admin-boundary.json").read_text())
expected = {
    "schema_version": "thehub_admin_boundary_consumer_v1",
    "contract_version": "1.0.0",
    "repository": REPO,
    "plane": "BOUNDED_OPERATIONAL",
    "federation_global_admin": False,
    "token_audience": "repository-operation",
    "hub_outage_behavior": "LOCAL_OPERATIONS_CONTINUE_GLOBAL_MUTATIONS_FAIL_CLOSED",
    "admin_kit_allowed": False,
}
if manifest != expected:
    fail("manifest differs from exact bounded-operational contract")

paths = subprocess.run(
    ["git", "ls-files"],
    cwd=ROOT,
    check=True,
    text=True,
    capture_output=True,
).stdout.splitlines()
scanned = 0
for rel in paths:
    excluded = rel.startswith(("docs/", "reports/", "tests/", ".federation/"))
    if excluded or rel == "scripts/check_admin_boundary.py":
        continue
    if Path(rel).suffix.lower() not in SOURCE_SUFFIXES:
        continue
    content = (ROOT / rel).read_text(encoding="utf-8", errors="ignore")
    scanned += 1
    hit = next((token for token in FORBIDDEN if token in content), None)
    if hit:
        fail(f"{rel}: prohibited federation-admin capability marker {hit!r}")

print(f"ADMIN_BOUNDARY_PASS repo={REPO} scanned={scanned}")
