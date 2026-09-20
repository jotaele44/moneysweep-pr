"""Audit MoneySweep v4 source-to-domain conformance.

This audit is intentionally read-only. It validates the frozen 167-source
mapping denominator and distinguishes structural conformance from bounded
source-lineage blockers. PARTIAL rows are never silently treated as MAPPED.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "manifests" / "v4" / "v01_source_domain_mapping.csv"
DOMAINS = ROOT / "architecture" / "v4" / "domain_registry.yaml"
CONTRACT = ROOT / "architecture" / "v4" / "source_mapping_contract.yaml"
CONTRADICTIONS = ROOT / "reports" / "v4" / "v01_contradictions.json"

_ALLOWED_STATES = {"MAPPED", "PARTIAL", "UNMAPPED", "UNRESOLVED"}


def _rows() -> list[dict[str, str]]:
    with MAPPING.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def audit() -> dict[str, Any]:
    rows = _rows()
    domains = set(yaml.safe_load(DOMAINS.read_text(encoding="utf-8"))["domains"])
    support = set(
        yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))["core_support_capabilities"]
    )
    contradictions = json.loads(CONTRADICTIONS.read_text(encoding="utf-8"))["contradictions"]

    ids = [row["source_id"] for row in rows]
    duplicate_ids = sorted({source_id for source_id in ids if ids.count(source_id) > 1})
    invalid_states = sorted(
        row["source_id"] for row in rows if row["mapping_state"] not in _ALLOWED_STATES
    )

    invalid_targets: list[dict[str, str]] = []
    empty_targets: list[str] = []
    for row in rows:
        targets = [value for value in row["targets"].split(";") if value]
        if not targets:
            empty_targets.append(row["source_id"])
        for target in targets:
            if target not in domains and target not in support:
                invalid_targets.append({"source_id": row["source_id"], "target": target})

    partial_ids = sorted(
        row["source_id"] for row in rows if row["mapping_state"] == "PARTIAL"
    )
    mapped_ids = sorted(row["source_id"] for row in rows if row["mapping_state"] == "MAPPED")
    unresolved_ids = sorted(
        row["source_id"]
        for row in rows
        if row["mapping_state"] in {"UNMAPPED", "UNRESOLVED"}
    )

    blocker_coverage: set[str] = set()
    for contradiction in contradictions:
        if contradiction.get("adjudication_state") != "OPEN_BLOCKED_SOURCE_LINEAGE":
            continue
        blocker_coverage.update(contradiction.get("source_family_ids") or [])

    uncovered_partials = sorted(set(partial_ids) - blocker_coverage)
    stale_blockers = sorted(blocker_coverage - set(partial_ids))

    structural_errors = []
    if len(rows) != 167:
        structural_errors.append(f"mapping row count {len(rows)} != 167")
    if len(set(ids)) != 167:
        structural_errors.append(f"unique source ID count {len(set(ids))} != 167")
    if duplicate_ids:
        structural_errors.append(f"duplicate source IDs: {duplicate_ids}")
    if invalid_states:
        structural_errors.append(f"invalid mapping states: {invalid_states}")
    if empty_targets:
        structural_errors.append(f"empty targets: {empty_targets}")
    if invalid_targets:
        structural_errors.append(f"invalid targets: {invalid_targets}")
    if unresolved_ids:
        structural_errors.append(f"unmapped/unresolved sources: {unresolved_ids}")
    if uncovered_partials:
        structural_errors.append(f"partial rows without explicit blocker: {uncovered_partials}")
    if stale_blockers:
        structural_errors.append(f"blockers not represented as PARTIAL: {stale_blockers}")

    state = "FAIL" if structural_errors else ("OPEN" if partial_ids else "PASS")
    return {
        "version": "v4.0.0-rc1",
        "audit": "DOMAIN_CONFORMANCE",
        "state": state,
        "source_count": len(rows),
        "unique_source_ids": len(set(ids)),
        "mapped_count": len(mapped_ids),
        "partial_count": len(partial_ids),
        "partial_source_ids": partial_ids,
        "unmapped_or_unresolved_count": len(unresolved_ids),
        "bounded_blocker_count": len(blocker_coverage),
        "bounded_blocker_source_ids": sorted(blocker_coverage),
        "structural_errors": structural_errors,
        "arithmetic_closure": (
            "PASS"
            if len(mapped_ids) + len(partial_ids) + len(unresolved_ids) == len(rows)
            else "FAIL"
        ),
    }


def main() -> int:
    report = audit()
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["state"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
