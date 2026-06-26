#!/usr/bin/env python3
"""Validate source-registry alignment with top-form control metadata.

This is a metadata-only validator. It does not execute producers, make network
calls, require API keys, or assert that sources are materialized.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CSV_REPORT = REPO_ROOT / "reports" / "source_registry_top_form_alignment.csv"
MD_REPORT = REPO_ROOT / "reports" / "source_registry_top_form_alignment.md"

ALLOWED_REFRESH = {"daily", "weekly", "monthly", "quarterly", "yearly", "ad_hoc", "unknown"}
# Sources that need explicit operator review yet carry no auth/manual marker that
# infer_blocker_type would otherwise catch. prasa/oficina_contralor were dropped
# here once the registry set their authentication to ``manual_export`` (they now
# resolve to the ``manual_required`` blocker via that path); cor3 (auth=none,
# recovery.pr.gov scrape) is the residual that still needs the explicit flag.
OPERATOR_REVIEW_REQUIRED = {"cor3"}

REQUIRED_COLUMNS = [
    "source_id",
    "family",
    "required",
    "authentication",
    "intake_mode",
    "refresh_frequency",
    "blocker_type",
    "alignment_status",
    "has_expected_outputs",
    "has_validation_threshold",
    "manual_drop_dir",
    "producer_script",
    "issue",
]


def _load_sources(root: Path) -> list[dict[str, Any]]:
    from moneysweep.runtime.source_registry import all_sources

    return all_sources(root)


def infer_intake_mode(source: dict[str, Any]) -> str:
    auth = source.get("authentication") or ""
    endpoint = source.get("endpoint_url") or ""
    producer = source.get("producer_script") or ""

    if auth == "manual_export":
        return "manual_export"
    if auth.startswith("api_key:"):
        return "api_key"
    if producer.startswith("scripts/ingest_"):
        return "static_file"
    if "api." in endpoint or "api/" in endpoint or "data-services" in endpoint:
        return "api"
    if endpoint:
        return "scrape"
    if producer:
        return "derived"
    return "unknown"


def infer_refresh_frequency(source: dict[str, Any]) -> str:
    value = (source.get("refresh_frequency") or source.get("update_cadence") or "unknown").strip()
    return value if value in ALLOWED_REFRESH else "unknown"


def _has_path_traversal(path_value: str) -> bool:
    return ".." in Path(path_value).parts


def infer_blocker_type(root: Path, source: dict[str, Any]) -> str:
    sid = source.get("source_id") or ""
    auth = source.get("authentication") or ""
    producer = source.get("producer_script") or ""
    expected_outputs = source.get("expected_outputs") or []
    threshold = source.get("validation_threshold") or {}
    required = bool(source.get("required"))

    if producer and _has_path_traversal(producer):
        return "path_traversal"
    if producer.startswith("archive/") and required:
        return "required_archived"
    if required and (not producer or not (root / producer).exists()):
        return "producer_missing"
    if required and not expected_outputs:
        return "output_missing"
    if required and not threshold.get("min_rows"):
        return "schema_threshold"
    if auth.startswith("api_key:"):
        return "auth_required"
    if auth == "manual_export":
        return "manual_required"
    if sid in OPERATOR_REVIEW_REQUIRED:
        return "manual_review_required"
    return "none"


def assess_source(root: Path, source: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []

    sid = source.get("source_id") or ""
    family = source.get("family") or ""
    auth = source.get("authentication") or ""
    producer = source.get("producer_script") or ""
    expected_outputs = source.get("expected_outputs") or []
    threshold = source.get("validation_threshold") or {}
    required = bool(source.get("required"))
    manual_drop_dir = source.get("manual_drop_dir") or ""

    if not sid:
        issues.append("missing source_id")
    if "required" not in source:
        issues.append("missing required flag")
    if required and not producer:
        issues.append("required source missing producer_script")
    if producer and _has_path_traversal(producer):
        issues.append("producer_script path traversal")
    if required and not expected_outputs:
        issues.append("required source missing expected_outputs")
    if required and not threshold.get("min_rows"):
        issues.append("required source missing validation_threshold.min_rows")
    if auth == "manual_export" and not manual_drop_dir:
        issues.append("manual_export source missing manual_drop_dir")
    if auth.startswith("api_key:") and not auth.split(":", 1)[1].strip():
        issues.append("api_key authentication missing env var name")

    blocker = infer_blocker_type(root, source)
    if issues:
        alignment_status = "error"
    elif blocker in {"auth_required", "manual_required", "manual_review_required"}:
        alignment_status = "warning"
    else:
        alignment_status = "aligned"

    return {
        "source_id": sid,
        "family": family,
        "required": required,
        "authentication": auth,
        "intake_mode": infer_intake_mode(source),
        "refresh_frequency": infer_refresh_frequency(source),
        "blocker_type": blocker,
        "alignment_status": alignment_status,
        "has_expected_outputs": bool(expected_outputs),
        "has_validation_threshold": bool(threshold),
        "manual_drop_dir": manual_drop_dir,
        "producer_script": producer,
        "issue": "; ".join(issues),
    }


def build_alignment(root: Path = REPO_ROOT) -> list[dict[str, Any]]:
    return [assess_source(root, source) for source in _load_sources(root)]


def write_csv(rows: list[dict[str, Any]], path: Path = CSV_REPORT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in REQUIRED_COLUMNS})


def write_markdown(rows: list[dict[str, Any]], path: Path = MD_REPORT) -> None:
    counts = Counter(row["alignment_status"] for row in rows)
    blockers = Counter(row["blocker_type"] for row in rows)
    intake = Counter(row["intake_mode"] for row in rows)

    lines = [
        "# Source Registry Top-Form Alignment",
        "",
        "This report maps the source registry to the top-form control vocabulary.",
        "",
        "It does not replace source materialization statuses and does not prove source materialization.",
        "",
        "## Summary",
        "",
        f"- Total sources: {len(rows)}",
        f"- Aligned: {counts.get('aligned', 0)}",
        f"- Warnings: {counts.get('warning', 0)}",
        f"- Errors: {counts.get('error', 0)}",
        "",
        "## Intake Modes",
        "",
    ]

    for key, value in sorted(intake.items()):
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Blocker Types", ""])

    for key, value in sorted(blockers.items()):
        lines.append(f"- `{key}`: {value}")

    surfaced = [row for row in rows if row["alignment_status"] != "aligned"]
    if surfaced:
        lines.extend(["", "## Warnings and Errors", ""])
        lines.append("| source_id | alignment_status | blocker_type | issue |")
        lines.append("|---|---|---|---|")
        for row in surfaced:
            issue = row["issue"] or "metadata aligned; operational blocker/review signal"
            lines.append(
                f"| `{row['source_id']}` | {row['alignment_status']} | "
                f"{row['blocker_type']} | {issue} |"
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate(rows: list[dict[str, Any]]) -> list[str]:
    return [
        f"{row['source_id']}: {row['issue']}" for row in rows if row["alignment_status"] == "error"
    ]


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--write-report", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    rows = build_alignment(args.root)
    errors = validate(rows)

    if args.write_report:
        write_csv(rows, args.root / "reports" / "source_registry_top_form_alignment.csv")
        write_markdown(rows, args.root / "reports" / "source_registry_top_form_alignment.md")

    payload = {
        "ok": not errors,
        "total_sources": len(rows),
        "status_counts": dict(Counter(row["alignment_status"] for row in rows)),
        "blocker_counts": dict(Counter(row["blocker_type"] for row in rows)),
        "errors": errors,
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    elif errors:
        for error in errors:
            print(f"ERROR: {error}")
    else:
        print("source registry top-form alignment passed")

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
