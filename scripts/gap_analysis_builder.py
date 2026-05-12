"""Build gap analysis report comparing declared vs materialized source outputs.

Reads:
  registries/source_registry.json
  data/staging/processed/**  (checks existence + size of expected_outputs)

Writes:
  reports/gap_analysis_report.csv
  reports/gap_analysis_report.json

Usage:
  python3 scripts/gap_analysis_builder.py
  python3 scripts/gap_analysis_builder.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MIN_ROWS_FOR_POPULATED = 1
HIGH_VALUE_OBLIGATION_THRESHOLD = 1_000_000_000.0  # $1B marks critical sources


def _read_registry(root: Path) -> list[dict]:
    path = root / "registries" / "source_registry.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("sources", [])
    except Exception:
        return []


def _file_status(root: Path, rel_path: str) -> dict:
    p = root / rel_path
    if not p.exists():
        return {"status": "missing", "size_bytes": 0, "row_count": 0}
    size = p.stat().st_size
    if size == 0:
        return {"status": "empty", "size_bytes": 0, "row_count": 0}
    row_count = 0
    if p.suffix.lower() == ".csv":
        try:
            with p.open(encoding="utf-8-sig", newline="") as f:
                row_count = max(0, sum(1 for _ in f) - 1)  # subtract header
        except Exception:
            pass
    else:
        row_count = -1  # non-CSV: size is the proxy
    if row_count == 0 and size > 10:
        # Header-only CSV
        return {"status": "header_only", "size_bytes": size, "row_count": 0}
    return {"status": "present", "size_bytes": size, "row_count": row_count}


def build_gap_analysis(root: Path) -> dict[str, Any]:
    sources = _read_registry(root)
    records: list[dict] = []
    summary: dict[str, int] = {
        "total_sources": 0, "required_sources": 0,
        "fully_materialized": 0, "partially_materialized": 0,
        "not_materialized": 0, "optional_not_materialized": 0,
    }

    for src in sources:
        sid = src.get("source_id", "")
        required = bool(src.get("required", False))
        family = src.get("family", "")
        auth = src.get("authentication", "")
        expected = src.get("expected_outputs", [])
        threshold = src.get("validation_threshold", {})
        min_rows = threshold.get("min_rows", 1)

        summary["total_sources"] += 1
        if required:
            summary["required_sources"] += 1

        file_statuses = []
        for rel in expected:
            fs = _file_status(root, rel)
            fs["path"] = rel
            file_statuses.append(fs)

        present = [f for f in file_statuses if f["status"] == "present"]
        missing = [f for f in file_statuses if f["status"] == "missing"]
        empty = [f for f in file_statuses if f["status"] in ("empty", "header_only")]

        if not expected:
            source_status = "no_outputs_declared"
        elif missing and not present:
            source_status = "not_materialized"
        elif missing or empty:
            source_status = "partially_materialized"
        else:
            # All present — check min_rows for CSVs
            under_threshold = [f for f in present if f["row_count"] != -1 and f["row_count"] < min_rows]
            source_status = "below_threshold" if under_threshold else "fully_materialized"

        if source_status == "fully_materialized":
            summary["fully_materialized"] += 1
        elif source_status in ("partially_materialized", "below_threshold"):
            summary["partially_materialized"] += 1
        elif source_status == "not_materialized":
            if required:
                summary["not_materialized"] += 1
            else:
                summary["optional_not_materialized"] += 1

        total_rows = sum(f["row_count"] for f in present if f["row_count"] > 0)

        records.append({
            "source_id": sid,
            "family": family,
            "required": required,
            "authentication": auth,
            "expected_output_count": len(expected),
            "present_count": len(present),
            "missing_count": len(missing),
            "empty_count": len(empty),
            "source_status": source_status,
            "total_rows_present": total_rows,
            "min_rows_threshold": min_rows,
            "first_expected_output": expected[0] if expected else "",
            "blocker_notes": src.get("notes", "")[:200] if src.get("notes") else "",
        })

    records.sort(key=lambda r: (
        0 if r["required"] else 1,
        0 if r["source_status"] == "not_materialized" else
        1 if r["source_status"] == "partially_materialized" else
        2 if r["source_status"] == "below_threshold" else 3,
        r["source_id"],
    ))

    reports_dir = root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    csv_path = reports_dir / "gap_analysis_report.csv"
    if records:
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(records[0].keys()), extrasaction="ignore")
            w.writeheader()
            w.writerows(records)
    else:
        csv_path.write_text("", encoding="utf-8")

    coverage_rate = summary["fully_materialized"] / summary["total_sources"] if summary["total_sources"] else 0.0
    required_coverage = (
        (summary["required_sources"] - summary["not_materialized"]) / summary["required_sources"]
        if summary["required_sources"] else 1.0
    )

    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": "r5_v1",
        **summary,
        "coverage_rate": round(coverage_rate, 4),
        "required_coverage_rate": round(required_coverage, 4),
        "outputs": [
            "reports/gap_analysis_report.csv",
            "reports/gap_analysis_report.json",
        ],
    }

    json_path = reports_dir / "gap_analysis_report.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = p.parse_args(argv)
    print(json.dumps(build_gap_analysis(Path(a.root)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
