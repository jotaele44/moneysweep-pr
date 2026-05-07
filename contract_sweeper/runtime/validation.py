"""Validation helpers for raw and normalized ingestion payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    """Validation status + diagnostics."""

    ok: bool
    missing_fields: list[str]
    row_count: int
    completeness: dict[str, float]


def validate_required_fields(rows: list[dict[str, Any]], required_fields: list[str]) -> ValidationResult:
    """Validate required fields and compute field-level completeness."""

    if not rows:
        return ValidationResult(
            ok=False,
            missing_fields=required_fields,
            row_count=0,
            completeness={field: 0.0 for field in required_fields},
        )

    completeness: dict[str, float] = {}
    missing: list[str] = []

    for field in required_fields:
        populated = 0
        for row in rows:
            value = row.get(field)
            if value is not None and str(value).strip() != "":
                populated += 1
        ratio = populated / len(rows)
        completeness[field] = round(ratio, 4)
        if ratio == 0:
            missing.append(field)

    return ValidationResult(
        ok=len(missing) == 0,
        missing_fields=missing,
        row_count=len(rows),
        completeness=completeness,
    )
