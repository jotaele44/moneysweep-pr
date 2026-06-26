#!/usr/bin/env python3
"""Validate moneysweep-pr top-form development control artifacts.

This script intentionally validates only lightweight control artifacts:
- docs/TOP_FORM_DEVELOPMENT_CHECKLIST.md
- reports/top_form_gap_matrix.csv
- schemas/top_form_gap_matrix.schema.json

It does not run source producers, mutate repo state, or require network access.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Iterable


_REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_DOC = _REPO_ROOT / "docs" / "TOP_FORM_DEVELOPMENT_CHECKLIST.md"
REQUIRED_MATRIX = _REPO_ROOT / "reports" / "top_form_gap_matrix.csv"
REQUIRED_SCHEMA = _REPO_ROOT / "schemas" / "top_form_gap_matrix.schema.json"

REQUIRED_COLUMNS = [
    "gate",
    "item",
    "status",
    "priority",
    "owner",
    "file_or_source",
    "next_action",
]

ALLOWED_STATUSES = {
    "done",
    "partial",
    "missing",
    "blocked",
    "manual_required",
    "auth_required",
    "unknown",
}

ALLOWED_PRIORITIES = {"P0", "P1", "P2", "P3"}

REQUIRED_GATES = {
    "source_registry",
    "required_sources",
    "federal_procurement",
    "entity_master",
    "local_contracts",
    "influence",
    "debt_fiscal",
    "gis",
    "graph_export",
    "dashboard",
    "foia",
    "testing",
}

REQUIRED_DOC_HEADINGS = [
    "# moneysweep-pr Top-Form Development Checklist",
    "## Purpose",
    "## Status Vocabulary",
    "## Evidence Tiers",
    "## Production Gates",
    "### Gate 1: Source Registry Lock",
    "### Gate 2: Required Source Materialization",
    "### Gate 3: Federal Procurement Spine",
    "### Gate 4: Puerto Rico Local Contract Intake",
    "### Gate 5: Entity Master",
    "### Gate 6: Influence Layer",
    "### Gate 7: Debt / Fiscal Control Layer",
    "### Gate 8: GIS / Infrastructure Layer",
    "### Gate 9: Graph Export",
    "### Gate 10: Analyst Product",
    "### Gate 11: Test / CI / Reproducibility",
    "## Production Complete Definition",
]


def _error(message: str) -> str:
    return f"ERROR: {message}"


def validate_doc(path: Path = REQUIRED_DOC) -> list[str]:
    """Validate the top-form checklist document."""

    errors: list[str] = []

    if not path.exists():
        return [_error(f"missing required doc: {path}")]

    content = path.read_text(encoding="utf-8")

    for heading in REQUIRED_DOC_HEADINGS:
        if heading not in content:
            errors.append(_error(f"missing heading in {path}: {heading}"))

    for tier in ("T1", "T2", "T3", "T4"):
        if tier not in content:
            errors.append(_error(f"missing evidence tier in {path}: {tier}"))

    for status in sorted(ALLOWED_STATUSES):
        if f"`{status}`" not in content and f"- {status}" not in content:
            errors.append(_error(f"missing status vocabulary in {path}: {status}"))

    return errors


def read_matrix(path: Path = REQUIRED_MATRIX) -> list[dict[str, str]]:
    """Read the top-form gap matrix as rows."""

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def validate_matrix(path: Path = REQUIRED_MATRIX) -> list[str]:
    """Validate top-form gap matrix structure and controlled values."""

    errors: list[str] = []

    if not path.exists():
        return [_error(f"missing required matrix: {path}")]

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []

        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            errors.append(_error(f"missing matrix columns: {missing}"))
            return errors

        rows = list(reader)

    if len(rows) < 25:
        errors.append(_error(f"matrix has too few rows: {len(rows)} < 25"))

    gates = set()

    for index, row in enumerate(rows, start=2):
        for column in REQUIRED_COLUMNS:
            value = (row.get(column) or "").strip()
            if not value:
                errors.append(_error(f"blank {column} at row {index}"))

        status = (row.get("status") or "").strip()
        if status and status not in ALLOWED_STATUSES:
            errors.append(_error(f"invalid status at row {index}: {status}"))

        priority = (row.get("priority") or "").strip()
        if priority and priority not in ALLOWED_PRIORITIES:
            errors.append(_error(f"invalid priority at row {index}: {priority}"))

        gate = (row.get("gate") or "").strip()
        if gate:
            gates.add(gate)

    missing_gates = REQUIRED_GATES - gates
    if missing_gates:
        errors.append(_error(f"missing required gates: {sorted(missing_gates)}"))

    return errors


def validate_schema(path: Path = REQUIRED_SCHEMA) -> list[str]:
    """Validate the top-form gap matrix JSON schema."""

    errors: list[str] = []

    if not path.exists():
        return [_error(f"missing required schema: {path}")]

    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [_error(f"invalid JSON schema {path}: {exc}")]

    required = parsed.get("required", [])
    for column in REQUIRED_COLUMNS:
        if column not in required:
            errors.append(_error(f"schema missing required column: {column}"))

    status_enum = parsed.get("properties", {}).get("status", {}).get("enum", [])
    for status in ALLOWED_STATUSES:
        if status not in status_enum:
            errors.append(_error(f"schema missing allowed status: {status}"))

    priority_enum = parsed.get("properties", {}).get("priority", {}).get("enum", [])
    for priority in ALLOWED_PRIORITIES:
        if priority not in priority_enum:
            errors.append(_error(f"schema missing allowed priority: {priority}"))

    return errors


def validate_all() -> list[str]:
    """Run all top-form control validations."""

    errors: list[str] = []
    errors.extend(validate_doc())
    errors.extend(validate_matrix())
    errors.extend(validate_schema())
    return errors


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint."""

    parser = argparse.ArgumentParser(description="Validate top-form development control artifacts.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON result instead of plain text.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    errors = validate_all()

    if args.json:
        print(json.dumps({"ok": not errors, "errors": errors}, indent=2))
    elif errors:
        for error in errors:
            print(error)
    else:
        print("top-form control validation passed")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
