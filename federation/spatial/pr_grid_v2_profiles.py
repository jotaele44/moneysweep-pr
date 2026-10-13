"""PR grid V2 domain profiles from Spiderweb-certified record bindings only."""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import pr_grid_v2_runtime as grid

PROFILE_VERSION = "pr-grid-v2-cell-profile/1.0"
DOMAIN_TYPES = {
    "aguayluz-pr": "water_hydrology",
    "skywatcher-pr": "flight_activity",
    "ovnis-pr": "anomalous_cases",
    "moneysweep-pr": "financial_activity",
    "centinelas-pr": "monitoring_state",
}


class ProfileError(ValueError):
    """Invalid authoritative binding receipt, metadata, or coverage evidence."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ProfileError("JSONL entries must be objects")
            rows.append(value)
    return rows


def build_profiles(
    *, pin_path: Path, records_path: Path, bindings_path: Path,
    receipt_path: Path, level: str, coverage_path: Path | None = None,
    requested_cells: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pin = grid.load_pin(pin_path, required_level=level)
    if pin.consumer not in DOMAIN_TYPES:
        raise ProfileError("only domain producers may materialize profiles")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    raw = bindings_path.read_bytes()
    expected = {
        "Grid_ID": grid.GRID_ID,
        "Grid_Version": grid.GRID_VERSION,
        "Grid_Manifest_SHA256": grid.GRID_MANIFEST_SHA256,
        "Binding_Schema_Version": grid.BINDING_SCHEMA_VERSION,
        "Binding_Output_SHA256": digest(raw),
        "Binding_Output_Bytes": len(raw),
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise ProfileError("authority binding receipt mismatch: " + field)
    bindings = load_jsonl(bindings_path)
    if len(bindings) != receipt.get("Binding_Row_Count"):
        raise ProfileError("authority binding row denominator mismatch")
    records = {}
    for row in load_jsonl(records_path):
        rid = row.get("Record_ID")
        if (row.get("Repository") != pin.consumer or not isinstance(rid, str)
                or not rid or not isinstance(row.get("Category"), str)
                or not row["Category"] or rid in records):
            raise ProfileError("invalid, duplicate or foreign record metadata")
        records[rid] = row
    grouped: dict[str, dict[str, str]] = defaultdict(dict)
    for binding in bindings:
        if binding.get("Grid_ID") != grid.GRID_ID or binding.get("Grid_Version") != grid.GRID_VERSION:
            raise ProfileError("incorrect grid version in binding")
        bound_level = grid.validate_level(binding.get("Grid_Level"))
        grid.validate_cell_id(binding.get("Cell_ID"), level=bound_level)
        if binding.get("Uncertainty_Class") != "EXACT" or binding.get("Binding_Method") != "COVERS":
            raise ProfileError("non-exact binding cannot enter exact-point profiles")
        if binding.get("Binding_State") not in ("INTERIOR", "EDGE_SHARED", "CORNER_SHARED"):
            raise ProfileError("unsupported boundary state")
        if binding.get("Repository") != pin.consumer:
            continue
        if bound_level != level or binding.get("Record_ID") not in records:
            raise ProfileError("binding level or record evidence mismatch")
        cid, rid = binding["Cell_ID"], binding["Record_ID"]
        if rid in grouped[cid]:
            raise ProfileError("duplicate record-cell binding")
        grouped[cid][rid] = binding["Binding_State"]
    covered = set()
    if coverage_path:
        coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        for field, value in {
            "Repository": pin.consumer, "Grid_ID": grid.GRID_ID,
            "Grid_Version": grid.GRID_VERSION, "Grid_Level": level,
            "Grid_Manifest_SHA256": grid.GRID_MANIFEST_SHA256,
            "Coverage_Manifest_State": "VERIFIED",
        }.items():
            if coverage.get(field) != value:
                raise ProfileError("coverage evidence mismatch: " + field)
        evidence = coverage.get("Coverage_Evidence_SHA256")
        if not isinstance(evidence, str) or len(evidence) != 64 or any(c not in "0123456789abcdef" for c in evidence):
            raise ProfileError("coverage evidence SHA256 is missing or invalid")
        cells = coverage.get("Coverage_Cells")
        if not isinstance(cells, list) or len(cells) != len(set(cells)):
            raise ProfileError("coverage cell set must be a unique list")
        covered = {grid.validate_cell_id(cid, level=level) for cid in cells}
    requested = {grid.validate_cell_id(cid, level=level) for cid in requested_cells}
    profiles = []
    states: dict[str, int] = defaultdict(int)
    for cid in sorted(set(grouped) | covered | requested):
        assigned = grouped.get(cid, {})
        ids = sorted(assigned)
        categories: dict[str, int] = defaultdict(int)
        for rid in ids:
            categories[records[rid]["Category"]] += 1
        state = "HAS_RECORDS" if ids else ("ZERO_RECORDS" if cid in covered else "NO_DATA")
        states[state] += 1
        profiles.append({
            "Schema_Version": PROFILE_VERSION,
            "Grid_Identity": grid.grid_identity(pin, level=level, cell_id=cid),
            "Repository": pin.consumer, "Profile_Type": DOMAIN_TYPES[pin.consumer],
            "Cell_ID": cid, "Data_State": state,
            "Coverage_State": "VERIFIED" if cid in covered else "UNKNOWN",
            "Record_Count": len(ids), "Category_Count": len(categories),
            "Categories": dict(sorted(categories.items())),
            "Top_Record_IDs": ids[:25],
            "Shared_Boundary_Record_Count": sum(s != "INTERIOR" for s in assigned.values()),
            "Identity_Default": "CANDIDATE_NOT_IDENTITY",
            "Geometry_Included": False,
        })
    provenance = {
        "Grid_Identity": grid.grid_identity(pin, level=level),
        "Repository": pin.consumer,
        "Binding_Receipt_SHA256": digest(receipt_path.read_bytes()),
        "Binding_Output_SHA256": digest(raw),
        "Records_SHA256": digest(records_path.read_bytes()),
        "Coverage_Manifest_SHA256": digest(coverage_path.read_bytes()) if coverage_path else None,
        "Input_Record_Count": len(records),
        "Profile_Count": len(profiles),
        "Data_State_Counts": dict(sorted(states.items())),
        "Migration_Class": "RECOMPUTED_FROM_SOURCE_COORDINATE",
        "Geometry_Copied": False,
        "State": "CANDIDATE_NOT_CANONICAL",
    }
    return profiles, provenance
