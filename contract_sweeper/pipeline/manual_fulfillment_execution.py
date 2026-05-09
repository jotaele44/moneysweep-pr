"""Manual file fulfillment execution utilities for R4.8H."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from contract_sweeper.pipeline.manual_import_dropzone import process_manual_import_dropzones, safe_int


def _normalize_manual_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda item: safe_int(item.get("priority"))):
        normalized.append(
            {
                "priority": str(safe_int(row.get("priority"))),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "target_dropzone_path": str(row.get("target_dropzone_path", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "accepted_filename_patterns": str(
                    row.get("accepted_filename_patterns", "")
                ).strip(),
                "required_columns": str(row.get("required_columns", "")).strip(),
                "validation_command": str(row.get("validation_command", "")).strip(),
                "source_url_or_portal": str(row.get("source_url_or_portal", "")).strip(),
                "producer_script": str(row.get("producer_script", "")).strip(),
            }
        )
    return normalized


def run_manual_fulfillment_execution(
    root: Path,
    *,
    manual_request_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Process manual-file dropzones and stage validated files.

    Returns a dict containing inventory rows, still-required rows, new manifests,
    and phase metrics.
    """

    normalized_rows = _normalize_manual_rows(manual_request_rows)

    inventory_rows, still_required_rows, new_manifests, metrics, forbidden = process_manual_import_dropzones(
        Path(root),
        manual_rows=normalized_rows,
    )

    return {
        "manual_inventory_rows": inventory_rows,
        "manual_still_required_rows": still_required_rows,
        "manual_new_manifests": new_manifests,
        "manual_forbidden_artifact_usage": bool(forbidden),
        "manual_requests_checked": int(metrics.get("manual_sources_checked", 0)),
        "manual_files_found": int(metrics.get("manual_files_found", 0)),
        "manual_files_validated": int(metrics.get("manual_files_validated", 0)),
        "manual_files_still_required": int(metrics.get("manual_files_still_required", 0)),
    }
