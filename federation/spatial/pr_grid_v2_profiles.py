"""PR grid V2 domain profiles from Spiderweb-certified record bindings only."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pr_grid_v2_runtime as grid

PROFILE_VERSION = "pr-grid-v2-cell-profile/1.2"
EXACT_PROFILE_METHODS = ("COVERS", "INTERSECTS_POSITIVE_AREA", "LINE_POSITIVE_LENGTH")
SET_PROFILE_POLICIES = {
    "ADMINISTRATIVE_SET": ("ADMINISTRATIVE_ONLY", "VERIFIED_ADMINISTRATIVE_GEOMETRY"),
    "DERIVED_SET": ("DERIVED", "VERIFIED_DERIVED_GEOMETRY"),
}
PROFILE_METHODS = EXACT_PROFILE_METHODS + tuple(SET_PROFILE_POLICIES)
MIGRATION_CLASSES = (
    "RECOMPUTED_FROM_SOURCE_COORDINATE",
    "RECOMPUTED_FROM_SOURCE_GEOMETRY",
    "VERIFIED_CROSSWALK",
)
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


def _migration_class(receipt: dict[str, Any]) -> str:
    value = receipt.get("Migration_Provenance_Class")
    if value is None and receipt.get("contract") == "pr-grid-v2-exact-point-binding-receipt/1.0":
        value = "RECOMPUTED_FROM_SOURCE_COORDINATE"
    if value not in MIGRATION_CLASSES:
        raise ProfileError("authority binding receipt lacks a supported migration provenance class")
    return str(value)


def _validate_binding_receipt(
    *,
    receipt_path: Path,
    bindings_path: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise ProfileError("authority binding receipt must be an object")
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
    return receipt, bindings, _migration_class(receipt)


def _records(
    *,
    records_path: Path,
    consumer: str,
) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in load_jsonl(records_path):
        rid = row.get("Record_ID")
        if (
            row.get("Repository") != consumer
            or not isinstance(rid, str)
            or not rid
            or not isinstance(row.get("Category"), str)
            or not row["Category"]
            or rid in records
        ):
            raise ProfileError("invalid, duplicate or foreign record metadata")
        records[rid] = row
    return records


def _validated_binding_index(
    *,
    bindings: Iterable[dict[str, Any]],
    consumer: str,
    level: str,
    record_ids: set[str] | None = None,
) -> dict[str, dict[str, tuple[str, str, str]]]:
    grouped: dict[str, dict[str, tuple[str, str, str]]] = defaultdict(dict)
    for binding in bindings:
        if (
            binding.get("Grid_ID") != grid.GRID_ID
            or binding.get("Grid_Version") != grid.GRID_VERSION
        ):
            raise ProfileError("incorrect grid version in binding")
        bound_level = grid.validate_level(binding.get("Grid_Level"))
        grid.validate_cell_id(binding.get("Cell_ID"), level=bound_level)
        method = binding.get("Binding_Method")
        if method not in PROFILE_METHODS:
            raise ProfileError("unsupported binding method")
        uncertainty = binding.get("Uncertainty_Class")
        if method in EXACT_PROFILE_METHODS:
            if uncertainty != "EXACT":
                raise ProfileError("exact binding method requires Uncertainty_Class=EXACT")
        else:
            expected_uncertainty, expected_geometry_state = SET_PROFILE_POLICIES[str(method)]
            if uncertainty != expected_uncertainty:
                raise ProfileError(
                    f"{method} requires Uncertainty_Class={expected_uncertainty}"
                )
            if binding.get("Geometry_State") != expected_geometry_state:
                raise ProfileError(
                    f"{method} requires Geometry_State={expected_geometry_state}"
                )
            if binding.get("Confidence") is not None:
                raise ProfileError(f"{method} requires Confidence=null")
        state = binding.get("Binding_State")
        if state not in ("INTERIOR", "EDGE_SHARED", "CORNER_SHARED"):
            raise ProfileError("unsupported boundary state")
        if method in ("INTERSECTS_POSITIVE_AREA", "ADMINISTRATIVE_SET", "DERIVED_SET"):
            area = binding.get("Overlap_Area_m2")
            fraction = binding.get("Cell_Coverage_Fraction")
            if (
                state != "INTERIOR"
                or not isinstance(area, (int, float))
                or isinstance(area, bool)
                or area <= 0
                or not isinstance(fraction, (int, float))
                or isinstance(fraction, bool)
                or fraction <= 0
                or fraction > 1
            ):
                raise ProfileError("invalid positive-area binding")
        elif method == "LINE_POSITIVE_LENGTH":
            length = binding.get("Length_In_Cell_m")
            if (
                state != "INTERIOR"
                or not isinstance(length, (int, float))
                or isinstance(length, bool)
                or length <= 0
            ):
                raise ProfileError("invalid positive-length exact binding")
        if binding.get("Repository") != consumer:
            continue
        if bound_level != level:
            raise ProfileError("binding level mismatch")
        rid = binding.get("Record_ID")
        if not isinstance(rid, str) or not rid:
            raise ProfileError("binding Record_ID is missing")
        if record_ids is not None and rid not in record_ids:
            continue
        cid = str(binding["Cell_ID"])
        if rid in grouped[cid]:
            raise ProfileError("duplicate record-cell binding")
        grouped[cid][rid] = (str(state), str(method), str(uncertainty))
    return grouped


def _coverage_cells(
    *,
    coverage_path: Path | None,
    consumer: str,
    level: str,
) -> set[str]:
    if coverage_path is None:
        return set()
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    for field, value in {
        "Repository": consumer,
        "Grid_ID": grid.GRID_ID,
        "Grid_Version": grid.GRID_VERSION,
        "Grid_Level": level,
        "Grid_Manifest_SHA256": grid.GRID_MANIFEST_SHA256,
        "Coverage_Manifest_State": "VERIFIED",
    }.items():
        if coverage.get(field) != value:
            raise ProfileError("coverage evidence mismatch: " + field)
    evidence = coverage.get("Coverage_Evidence_SHA256")
    if (
        not isinstance(evidence, str)
        or len(evidence) != 64
        or any(c not in "0123456789abcdef" for c in evidence)
    ):
        raise ProfileError("coverage evidence SHA256 is missing or invalid")
    cells = coverage.get("Coverage_Cells")
    if not isinstance(cells, list) or len(cells) != len(set(cells)):
        raise ProfileError("coverage cell set must be a unique list")
    return {grid.validate_cell_id(cid, level=level) for cid in cells}


def build_profiles(
    *,
    pin_path: Path,
    records_path: Path,
    bindings_path: Path,
    receipt_path: Path,
    level: str,
    coverage_path: Path | None = None,
    requested_cells: tuple[str, ...] = (),
    cell_filter: tuple[str, ...] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pin = grid.load_pin(pin_path, required_level=level)
    if pin.consumer not in DOMAIN_TYPES:
        raise ProfileError("only domain producers may materialize profiles")
    receipt, bindings, migration_class = _validate_binding_receipt(
        receipt_path=receipt_path,
        bindings_path=bindings_path,
    )
    records = _records(records_path=records_path, consumer=pin.consumer)
    grouped = _validated_binding_index(
        bindings=bindings,
        consumer=pin.consumer,
        level=level,
    )
    for assigned in grouped.values():
        for rid in assigned:
            if rid not in records:
                raise ProfileError("binding record evidence mismatch")
    covered = _coverage_cells(
        coverage_path=coverage_path,
        consumer=pin.consumer,
        level=level,
    )
    requested = {grid.validate_cell_id(cid, level=level) for cid in requested_cells}
    selected = None
    if cell_filter is not None:
        selected = {grid.validate_cell_id(cid, level=level) for cid in cell_filter}
    all_cells = set(grouped) | covered | requested
    if selected is not None:
        all_cells &= selected

    profiles = []
    states: dict[str, int] = defaultdict(int)
    for cid in sorted(all_cells):
        assigned = grouped.get(cid, {})
        ids = sorted(assigned)
        categories: dict[str, int] = defaultdict(int)
        method_counts: dict[str, int] = defaultdict(int)
        uncertainty_counts: dict[str, int] = defaultdict(int)
        for rid in ids:
            categories[records[rid]["Category"]] += 1
            _, method, uncertainty = assigned[rid]
            method_counts[method] += 1
            uncertainty_counts[uncertainty] += 1
        state = "HAS_RECORDS" if ids else ("ZERO_RECORDS" if cid in covered else "NO_DATA")
        states[state] += 1
        profiles.append(
            {
                "Schema_Version": PROFILE_VERSION,
                "Grid_Identity": grid.grid_identity(pin, level=level, cell_id=cid),
                "Repository": pin.consumer,
                "Profile_Type": DOMAIN_TYPES[pin.consumer],
                "Cell_ID": cid,
                "Grid_Deep_Link": grid.build_grid_deep_link(
                    pin,
                    level=level,
                    cell_id=cid,
                ),
                "Data_State": state,
                "Coverage_State": "VERIFIED" if cid in covered else "UNKNOWN",
                "Record_Count": len(ids),
                "Category_Count": len(categories),
                "Categories": dict(sorted(categories.items())),
                "Top_Record_IDs": ids[:25],
                "Binding_Method_Counts": dict(sorted(method_counts.items())),
                "Uncertainty_Class_Counts": dict(sorted(uncertainty_counts.items())),
                "Exact_Record_Count": uncertainty_counts.get("EXACT", 0),
                "Non_Exact_Record_Count": len(ids) - uncertainty_counts.get("EXACT", 0),
                "Shared_Boundary_Record_Count": sum(
                    state != "INTERIOR" for state, _, _ in assigned.values()
                ),
                "Migration_Class": migration_class,
                "Identity_Default": "CANDIDATE_NOT_IDENTITY",
                "Geometry_Included": False,
            }
        )
    provenance = {
        "Grid_Identity": grid.grid_identity(pin, level=level),
        "Repository": pin.consumer,
        "Binding_Receipt_SHA256": digest(receipt_path.read_bytes()),
        "Binding_Output_SHA256": digest(bindings_path.read_bytes()),
        "Records_SHA256": digest(records_path.read_bytes()),
        "Coverage_Manifest_SHA256": digest(coverage_path.read_bytes()) if coverage_path else None,
        "Input_Record_Count": len(records),
        "Profile_Count": len(profiles),
        "Data_State_Counts": dict(sorted(states.items())),
        "Migration_Class": migration_class,
        "Accepted_Binding_Methods": list(PROFILE_METHODS),
        "Accepted_Set_Policies": {
            method: {
                "Uncertainty_Class": uncertainty,
                "Geometry_State": geometry_state,
                "Confidence": None,
            }
            for method, (uncertainty, geometry_state) in SET_PROFILE_POLICIES.items()
        },
        "Geometry_Copied": False,
        "State": "CANDIDATE_NOT_CANONICAL",
    }
    return profiles, provenance


def compute_impacted_cells(
    *,
    pin_path: Path,
    previous_bindings_path: Path,
    previous_receipt_path: Path,
    bindings_path: Path,
    receipt_path: Path,
    level: str,
    changed_record_ids: tuple[str, ...] = (),
    changed_coverage_cells: tuple[str, ...] = (),
) -> tuple[str, ...]:
    pin = grid.load_pin(pin_path, required_level=level)
    old_receipt, old_bindings, _ = _validate_binding_receipt(
        receipt_path=previous_receipt_path,
        bindings_path=previous_bindings_path,
    )
    new_receipt, new_bindings, _ = _validate_binding_receipt(
        receipt_path=receipt_path,
        bindings_path=bindings_path,
    )
    if old_receipt.get("Grid_Manifest_SHA256") != new_receipt.get("Grid_Manifest_SHA256"):
        raise ProfileError("incremental refresh cannot cross grid manifest versions")
    changed = set(changed_record_ids)
    if not changed and not changed_coverage_cells:
        raise ProfileError("incremental refresh requires changed records or coverage cells")
    if any(not isinstance(rid, str) or not rid for rid in changed):
        raise ProfileError("changed Record_ID values must be non-empty strings")

    impacted = {
        grid.validate_cell_id(cid, level=level)
        for cid in changed_coverage_cells
    }
    for rows in (old_bindings, new_bindings):
        grouped = _validated_binding_index(
            bindings=rows,
            consumer=pin.consumer,
            level=level,
            record_ids=changed,
        )
        impacted.update(grouped)
    return tuple(sorted(impacted))


def build_incremental_profiles(
    *,
    pin_path: Path,
    records_path: Path,
    bindings_path: Path,
    receipt_path: Path,
    previous_bindings_path: Path,
    previous_receipt_path: Path,
    previous_profiles_path: Path,
    level: str,
    coverage_path: Path | None = None,
    changed_record_ids: tuple[str, ...] = (),
    changed_coverage_cells: tuple[str, ...] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    impacted = compute_impacted_cells(
        pin_path=pin_path,
        previous_bindings_path=previous_bindings_path,
        previous_receipt_path=previous_receipt_path,
        bindings_path=bindings_path,
        receipt_path=receipt_path,
        level=level,
        changed_record_ids=changed_record_ids,
        changed_coverage_cells=changed_coverage_cells,
    )
    profiles, receipt = build_profiles(
        pin_path=pin_path,
        records_path=records_path,
        bindings_path=bindings_path,
        receipt_path=receipt_path,
        coverage_path=coverage_path,
        level=level,
        requested_cells=impacted,
        cell_filter=impacted,
    )

    previous_rows = load_jsonl(previous_profiles_path)
    seen = set()
    for row in previous_rows:
        cid = row.get("Cell_ID")
        if not isinstance(cid, str) or cid in seen:
            raise ProfileError("previous profile snapshot has invalid or duplicate Cell_ID")
        grid.validate_cell_id(cid, level=level)
        identity = row.get("Grid_Identity")
        if not isinstance(identity, dict):
            raise ProfileError("previous profile snapshot lacks Grid_Identity")
        if (
            identity.get("Grid_ID") != grid.GRID_ID
            or identity.get("Grid_Version") != grid.GRID_VERSION
            or identity.get("Grid_Manifest_SHA256") != grid.GRID_MANIFEST_SHA256
        ):
            raise ProfileError("previous profile snapshot has incompatible grid identity")
        seen.add(cid)

    receipt.update(
        {
            "Refresh_Mode": "INCREMENTAL",
            "Output_Mode": "DELTA_UPSERT",
            "Changed_Record_IDs": sorted(set(changed_record_ids)),
            "Changed_Coverage_Cells": sorted(set(changed_coverage_cells)),
            "Impacted_Cell_IDs": list(impacted),
            "Impact_Cell_Count": len(impacted),
            "Previous_Binding_Output_SHA256": digest(previous_bindings_path.read_bytes()),
            "Previous_Binding_Receipt_SHA256": digest(previous_receipt_path.read_bytes()),
            "Previous_Profile_SHA256": digest(previous_profiles_path.read_bytes()),
            "Rollback_Target_SHA256": digest(previous_profiles_path.read_bytes()),
        }
    )
    return profiles, receipt
