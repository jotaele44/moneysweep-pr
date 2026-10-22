#!/usr/bin/env python3
"""Export exact federation observations for Spiderweb's PR Grid V2 binder.

The federation observation schema defines location as WGS84. This adapter does
not infer exactness from coordinate presence: admission additionally requires
attributes.grid_v2_coordinate_evidence_state=VERIFIED_SOURCE_COORDINATE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

EVIDENCE_STATE = "VERIFIED_SOURCE_COORDINATE"
SOURCE_CRS = "EPSG:4326"
CONTRACT = "pr-grid-v2-federation-observation-export/1.0"


class SourceExportError(ValueError):
    """Input violates the exact source-coordinate export contract."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    seen = set()
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise SourceExportError(f"{path}:{lineno}: expected object")
        rid = value.get("observation_id")
        if not isinstance(rid, str) or not rid:
            raise SourceExportError(f"{path}:{lineno}: observation_id is required")
        if rid in seen:
            raise SourceExportError(f"duplicate observation_id: {rid}")
        seen.add(rid)
        rows.append(value)
    return rows


def _finite(name: str, value: Any) -> float:
    if isinstance(value, bool):
        raise SourceExportError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise SourceExportError(f"{name} must be numeric") from exc
    if not math.isfinite(number):
        raise SourceExportError(f"{name} must be finite")
    return number


def project_observations(
    rows: list[dict[str, Any]],
    *,
    repository: str,
    allow_synthetic: bool = False,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    if not repository:
        raise SourceExportError("repository is required")

    sources = []
    records = []
    excluded: Counter[str] = Counter()
    for row in rows:
        rid = row["observation_id"]
        if row.get("synthetic") is True and not allow_synthetic:
            excluded["SYNTHETIC"] += 1
            continue
        location = row.get("location")
        if not isinstance(location, dict):
            excluded["NO_POINT_LOCATION"] += 1
            continue
        attributes = row.get("attributes")
        if not isinstance(attributes, dict):
            excluded["NO_EXACT_EVIDENCE"] += 1
            continue
        if attributes.get("grid_v2_coordinate_evidence_state") != EVIDENCE_STATE:
            excluded["NO_EXACT_EVIDENCE"] += 1
            continue

        lon = _finite("location.lon", location.get("lon"))
        lat = _finite("location.lat", location.get("lat"))
        if not (-180 <= lon <= 180 and -90 <= lat <= 90):
            raise SourceExportError(f"out-of-range WGS84 coordinate for {rid}")
        category = row.get("observation_type")
        if not isinstance(category, str) or not category:
            raise SourceExportError(f"observation_type is required for {rid}")

        sources.append(
            {
                "Repository": repository,
                "Record_ID": rid,
                "Source_X": lon,
                "Source_Y": lat,
                "Source_CRS": SOURCE_CRS,
                "Coordinate_Evidence_State": EVIDENCE_STATE,
                "Uncertainty_Class": "EXACT",
                "Spatial_Role": "POINT_LOCATION",
            }
        )
        records.append(
            {
                "Repository": repository,
                "Record_ID": rid,
                "Category": category,
            }
        )

    return sources, records, dict(sorted(excluded.items()))


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-out", type=Path, required=True)
    parser.add_argument("--records-out", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    parser.add_argument("--allow-synthetic", action="store_true")
    args = parser.parse_args()

    try:
        rows = _read_jsonl(args.observations)
        sources, records, excluded = project_observations(
            rows,
            repository=args.repository,
            allow_synthetic=args.allow_synthetic,
        )
    except (OSError, json.JSONDecodeError, SourceExportError) as exc:
        parser.exit(2, f"FAIL_CLOSED: {exc}\n")

    _write_jsonl(args.source_out, sources)
    _write_jsonl(args.records_out, records)
    receipt = {
        "contract": CONTRACT,
        "Repository": args.repository,
        "Source_Schema": "federation_observation.schema.json",
        "Source_CRS": SOURCE_CRS,
        "Coordinate_Evidence_State": EVIDENCE_STATE,
        "Input_SHA256": _digest(args.observations.read_bytes()),
        "Input_Bytes": args.observations.stat().st_size,
        "Input_Record_Count": len(rows),
        "Admitted_Record_Count": len(sources),
        "Excluded_Record_Count": len(rows) - len(sources),
        "Excluded_State_Counts": excluded,
        "Source_Output_SHA256": _digest(args.source_out.read_bytes()),
        "Source_Output_Bytes": args.source_out.stat().st_size,
        "Records_Output_SHA256": _digest(args.records_out.read_bytes()),
        "Records_Output_Bytes": args.records_out.stat().st_size,
        "Synthetic_Allowed": args.allow_synthetic,
        "Geometry_Generated": False,
        "Cell_ID_Assigned": False,
        "Receipt_State": "PASS",
    }
    args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_out.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
