"""External acquisition blocker packaging for R4.8I."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(raw: Any) -> int:
    try:
        return int(float(str(raw or "0").strip()))
    except (TypeError, ValueError):
        return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_markdown(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _manual_blocker_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: _safe_int(item.get("priority"))):
        out.append(
            {
                "blocker_type": "manual_file_required",
                "priority": _safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "required_action": "Provide validated manual file in dropzone",
                "reason": str(row.get("failure_reason", "")).strip() or "manual file still required",
                "review_status": str(row.get("review_status", "")).strip() or "pending_manual_file",
                "source_url_or_portal": str(row.get("source_url_or_portal", "")).strip(),
            }
        )
    return out


def _endpoint_blocker_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: _safe_int(item.get("priority"))):
        out.append(
            {
                "blocker_type": "endpoint_blocked",
                "priority": _safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "required_action": "Resolve endpoint access/availability and retry",
                "reason": str(row.get("failure_reason", "")).strip()
                or str(row.get("retry_status", "")).strip()
                or "endpoint still blocked",
                "review_status": str(row.get("review_status", "")).strip() or "pending_retry",
                "source_url_or_portal": str(row.get("source_url_or_portal", "")).strip(),
            }
        )
    return out


def _producer_blocker_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: _safe_int(item.get("priority"))):
        out.append(
            {
                "blocker_type": "producer_blocked",
                "priority": _safe_int(row.get("priority")),
                "source_family": str(row.get("source_family", "")).strip(),
                "expected_input": str(row.get("expected_input", "")).strip(),
                "target_output_path": str(row.get("target_output_path", "")).strip(),
                "required_action": "Resolve producer failure and retry",
                "reason": str(row.get("failure_reason", "")).strip()
                or str(row.get("retry_status", "")).strip()
                or "producer still blocked",
                "review_status": str(row.get("review_status", "")).strip() or "pending_retry",
                "source_url_or_portal": "",
            }
        )
    return out


def _to_markdown(
    *,
    generated_at: str,
    total_blockers: int,
    manual_count: int,
    endpoint_count: int,
    producer_count: int,
    blockers: list[dict[str, Any]],
) -> str:
    lines = [
        "# R4.8I External Acquisition Blocker Package",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Total unresolved blockers: `{total_blockers}`",
        f"- Manual file blockers: `{manual_count}`",
        f"- Endpoint blockers: `{endpoint_count}`",
        f"- Producer blockers: `{producer_count}`",
        "",
        "These blockers remain outside Codex control and require external file delivery, endpoint availability, and/or source access changes.",
        "",
        "## Blockers",
        "",
        "| Priority | Type | Source | Expected Input | Required Action | Reason |",
        "|---:|---|---|---|---|---|",
    ]
    for row in blockers:
        lines.append(
            "| "
            f"{_safe_int(row.get('priority'))} | "
            f"{str(row.get('blocker_type', ''))} | "
            f"{str(row.get('source_family', ''))} | "
            f"{str(row.get('expected_input', ''))} | "
            f"{str(row.get('required_action', ''))} | "
            f"{str(row.get('reason', '')).replace('|', '/')} |"
        )

    return "\n".join(lines) + "\n"


def build_external_acquisition_blocker_package(
    root: Path,
    *,
    manual_rows: list[dict[str, Any]],
    endpoint_rows: list[dict[str, Any]],
    producer_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], int]:
    """Build and write R4.8I external blocker package artifacts."""

    root = Path(root)
    exports_dir = root / "data" / "exports"

    generated_at = _utc_now()

    manual_blockers = _manual_blocker_rows(manual_rows)
    endpoint_blockers = _endpoint_blocker_rows(endpoint_rows)
    producer_blockers = _producer_blocker_rows(producer_rows)

    all_blockers = manual_blockers + endpoint_blockers + producer_blockers
    all_blockers.sort(
        key=lambda row: (
            _safe_int(row.get("priority")),
            str(row.get("blocker_type", "")),
            str(row.get("expected_input", "")),
        )
    )

    payload = {
        "generated_at": generated_at,
        "phase": "R4.8I_MANUAL_FILE_DELIVERY_AND_AUTHORIZED_ENDPOINT_RETRY_EXECUTION",
        "external_blocker_count": len(all_blockers),
        "manual_blocker_count": len(manual_blockers),
        "endpoint_blocker_count": len(endpoint_blockers),
        "producer_blocker_count": len(producer_blockers),
        "outside_codex_control": True,
        "blockers": all_blockers,
    }

    markdown = _to_markdown(
        generated_at=generated_at,
        total_blockers=len(all_blockers),
        manual_count=len(manual_blockers),
        endpoint_count=len(endpoint_blockers),
        producer_count=len(producer_blockers),
        blockers=all_blockers,
    )

    _write_json(exports_dir / "external_acquisition_blocker_package_r4_8i.json", payload)
    _write_markdown(exports_dir / "external_acquisition_blocker_package_r4_8i.md", markdown)

    return payload, len(all_blockers)
