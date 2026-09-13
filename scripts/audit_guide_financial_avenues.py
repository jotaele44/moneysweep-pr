"""Audit the frozen Grant Thornton guide denominator against MoneySweep sources.

Set algebra is computed in the *guide canonical avenue universe*:

A = all frozen guide avenues.
B = guide avenues with at least one explicit base-registry source binding.

That projection makes B_ONLY=0 by construction. A separate source-level audit
classifies every one of the 158 base registry sources as INTERSECTION or B_ONLY;
that is the correct place to preserve MoneySweep sources outside this guide.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from moneysweep.runtime.source_registry import load_source_registry
from scripts.config import PROJECT_ROOT

GUIDE_REL = Path("registries/guide_financial_avenues_v1.yaml")
BINDINGS_REL = Path("registries/guide_financial_avenue_bindings_v1.yaml")
SOURCE_STATUS_REL = Path("reports/source_registry_status.csv")
OVERLAY_REL = Path("registries/source_registry_overlays/guide_financial_avenues_v1.yaml")

SOURCE_AUDIT_REL = Path("reports/guide_financial_avenue_source_audit_v1.csv")
AVENUE_AUDIT_REL = Path("reports/guide_financial_avenue_matrix_v1.csv")
METRICS_REL = Path("reports/guide_financial_avenue_set_metrics_v1.json")

ALLOWED_BINDING_STATES = {
    "AUTHORITATIVE_ROUTE",
    "SUPPORTING_ROUTE",
    "CANDIDATE_NOT_IDENTITY",
    "ABSENT",
}


def _yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected YAML mapping: {path}")
    return data


def _source_ids(registry: dict) -> list[str]:
    sources = registry.get("sources") or []
    ids = [str(item.get("source_id", "")).strip() for item in sources]
    if not ids or any(not value for value in ids):
        raise RuntimeError("source_registry contains null/empty source_id")
    if len(ids) != len(set(ids)):
        dupes = [key for key, count in Counter(ids).items() if count > 1]
        raise RuntimeError(f"source_registry duplicate source_id: {dupes}")
    return ids


def _status_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def load_inputs(root: Path = PROJECT_ROOT) -> dict:
    guide = _yaml(root / GUIDE_REL)
    bindings = _yaml(root / BINDINGS_REL)
    snapshot = bindings.get("base_registry_snapshot") or {}
    snapshot_path = (root / str(snapshot.get("source_ids_file", ""))).resolve()
    if not snapshot_path.is_relative_to(root.resolve()):
        raise RuntimeError(f"base source snapshot escapes repository root: {snapshot_path}")
    # The canonical MoneySweep source denominator is the effective registry,
    # including source-registry extensions and scoped metadata overrides. Reading
    # only registries/source_registry.yaml silently drops extension sources and
    # would corrupt the frozen 158-source denominator.
    registry = load_source_registry(root)
    overlay = _yaml(root / OVERLAY_REL)
    statuses = _status_rows(root / SOURCE_STATUS_REL)
    snapshot_rows = _status_rows(snapshot_path)
    return {
        "guide": guide,
        "bindings": bindings,
        "registry": registry,
        "overlay": overlay,
        "statuses": statuses,
        "snapshot_rows": snapshot_rows,
    }


def validate_inputs(inputs: dict) -> dict:
    guide = inputs["guide"]
    bindings = inputs["bindings"]
    registry = inputs["registry"]
    overlay = inputs["overlay"]
    statuses = inputs["statuses"]

    avenues = guide.get("avenues") or []
    avenue_ids = [str(x.get("avenue_id", "")) for x in avenues]
    canonicals = [str(x.get("canonical", "")) for x in avenues]
    if len(avenue_ids) != 30:
        raise RuntimeError(f"guide denominator drift: expected 30 avenues, got {len(avenue_ids)}")
    if len(avenue_ids) != len(set(avenue_ids)):
        raise RuntimeError("duplicate guide avenue_id")
    if len(canonicals) != len(set(canonicals)) or any(not x for x in canonicals):
        raise RuntimeError("duplicate/null guide canonical avenue")

    live_source_ids = _source_ids(registry)
    snapshot = bindings.get("base_registry_snapshot") or {}
    snapshot_rows = inputs["snapshot_rows"]
    source_ids = [str(row.get("source_id", "")).strip() for row in snapshot_rows]
    expected_count = int(snapshot.get("expected_source_count", 0))
    if len(source_ids) != expected_count:
        raise RuntimeError(
            f"base source denominator drift: expected={expected_count} observed={len(source_ids)}"
        )
    if any(not source_id for source_id in source_ids) or len(source_ids) != len(set(source_ids)):
        raise RuntimeError("base source snapshot contains null/duplicate source_id")
    observed_hash = hashlib.sha256(("\n".join(sorted(source_ids)) + "\n").encode()).hexdigest()
    expected_hash = str(snapshot.get("source_ids_sha256", ""))
    if observed_hash != expected_hash:
        raise RuntimeError(
            f"base source snapshot hash drift: expected={expected_hash} observed={observed_hash}"
        )
    missing_live = sorted(set(source_ids) - set(live_source_ids))
    if missing_live:
        raise RuntimeError(f"frozen base sources missing from live registry: {missing_live}")

    status_ids = [str(row.get("source_id", "")).strip() for row in statuses]
    if len(status_ids) != len(set(status_ids)):
        raise RuntimeError("source_registry_status duplicate source_id")
    if not set(source_ids) <= set(status_ids):
        missing_status = sorted(set(source_ids) - set(status_ids))
        raise RuntimeError(f"source_registry_status missing frozen sources: {missing_status}")

    mapping = bindings.get("bindings") or {}
    if set(mapping) != set(avenue_ids):
        raise RuntimeError(
            f"binding denominator mismatch: missing={sorted(set(avenue_ids) - set(mapping))} "
            f"extra={sorted(set(mapping) - set(avenue_ids))}"
        )

    unknown_sources: dict[str, list[str]] = {}
    for avenue_id, binding in mapping.items():
        state = str(binding.get("state", ""))
        if state not in ALLOWED_BINDING_STATES:
            raise RuntimeError(f"{avenue_id}: invalid binding state {state!r}")
        refs = [str(x) for x in (binding.get("source_ids") or [])]
        if state == "ABSENT" and refs:
            raise RuntimeError(f"{avenue_id}: ABSENT binding cannot carry source_ids")
        if state != "ABSENT" and not refs:
            raise RuntimeError(f"{avenue_id}: represented binding must carry source_ids")
        unknown = sorted(set(refs) - set(source_ids))
        if unknown:
            unknown_sources[avenue_id] = unknown
    if unknown_sources:
        raise RuntimeError(f"bindings reference unknown base source ids: {unknown_sources}")

    overlay_ids = [str(x.get("source_id", "")) for x in (overlay.get("sources") or [])]
    if len(overlay_ids) != len(set(overlay_ids)) or any(not x for x in overlay_ids):
        raise RuntimeError("guide overlay duplicate/null source_id")
    collisions = sorted(set(overlay_ids) & set(source_ids))
    if collisions:
        raise RuntimeError(f"guide overlay collides with base source ids: {collisions}")

    return {
        "avenue_ids": avenue_ids,
        "canonical_by_id": {str(x["avenue_id"]): str(x["canonical"]) for x in avenues},
        "source_ids": source_ids,
        "live_source_ids": live_source_ids,
        "status_by_id": {str(row["source_id"]): row for row in statuses},
        "overlay_ids": overlay_ids,
    }


def compute(inputs: dict, validated: dict) -> dict:
    mapping = inputs["bindings"]["bindings"]
    avenue_ids = set(validated["avenue_ids"])

    represented = {aid for aid, binding in mapping.items() if binding["state"] != "ABSENT"}
    intersection = avenue_ids & represented
    a_only = avenue_ids - represented
    b_only = represented - avenue_ids
    union = avenue_ids | represented
    symmetric_difference = avenue_ids ^ represented

    source_to_avenues: dict[str, list[str]] = defaultdict(list)
    source_to_states: dict[str, set[str]] = defaultdict(set)
    for avenue_id, binding in mapping.items():
        for source_id in binding.get("source_ids") or []:
            source_to_avenues[str(source_id)].append(avenue_id)
            source_to_states[str(source_id)].add(str(binding["state"]))

    bound_sources = set(source_to_avenues)
    source_universe = set(validated["source_ids"])
    source_intersection = source_universe & bound_sources
    source_b_only = source_universe - bound_sources

    return {
        "avenue_sets": {
            "A": sorted(avenue_ids),
            "B_GUIDE_PROJECTION": sorted(represented),
            "INTERSECTION": sorted(intersection),
            "A_ONLY": sorted(a_only),
            "B_ONLY": sorted(b_only),
            "UNION": sorted(union),
            "SYMMETRIC_DIFFERENCE": sorted(symmetric_difference),
        },
        "source_sets": {
            "SOURCE_UNIVERSE": sorted(source_universe),
            "INTERSECTION": sorted(source_intersection),
            "B_ONLY": sorted(source_b_only),
        },
        "source_to_avenues": source_to_avenues,
        "source_to_states": source_to_states,
    }


def metrics_payload(inputs: dict, validated: dict, computed: dict) -> dict:
    aset = computed["avenue_sets"]
    sset = computed["source_sets"]
    state_counts = Counter(
        str(binding["state"]) for binding in inputs["bindings"]["bindings"].values()
    )
    pipeline_counts = Counter(
        str(validated["status_by_id"][source_id].get("pipeline_status", "UNKNOWN"))
        for source_id in validated["source_ids"]
    )
    return {
        "schema_version": "guide_financial_avenue_set_metrics_v1",
        "scope_id": inputs["guide"]["scope_id"],
        "base_source_count": len(validated["source_ids"]),
        "guide_avenue_count": len(aset["A"]),
        "guide_projection": {
            "intersection_count": len(aset["INTERSECTION"]),
            "a_only_count": len(aset["A_ONLY"]),
            "b_only_count": len(aset["B_ONLY"]),
            "union_count": len(aset["UNION"]),
            "symmetric_difference_count": len(aset["SYMMETRIC_DIFFERENCE"]),
            "a_only": aset["A_ONLY"],
            "symmetric_difference": aset["SYMMETRIC_DIFFERENCE"],
        },
        "source_projection": {
            "intersection_count": len(sset["INTERSECTION"]),
            "b_only_count": len(sset["B_ONLY"]),
        },
        "binding_state_counts": dict(sorted(state_counts.items())),
        "pipeline_status_counts_all_158_sources": dict(sorted(pipeline_counts.items())),
        "proposed_overlay_source_ids": sorted(validated["overlay_ids"]),
        "certification_state": "OPEN",
        "certification_reason": (
            "Route coverage is not certification; authoritative materialization, exact category/identity bindings, "
            "temporal/provenance closure, and zero unresolved residue are not yet established for every avenue."
        ),
        "global_scope_note": (
            "The frozen 2021 guide explicitly states that it is not exhaustive; GUIDE_BOUNDED_100_PERCENT must "
            "never be promoted to a claim of complete Puerto Rico finance coverage."
        ),
    }


def write_outputs(root: Path, inputs: dict, validated: dict, computed: dict) -> dict:
    source_path = root / SOURCE_AUDIT_REL
    avenue_path = root / AVENUE_AUDIT_REL
    metrics_path = root / METRICS_REL
    source_path.parent.mkdir(parents=True, exist_ok=True)

    with source_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "source_id",
            "family",
            "pipeline_status",
            "guide_relation",
            "guide_avenue_ids",
            "binding_states",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for source_id in validated["source_ids"]:
            status = validated["status_by_id"][source_id]
            avenues = sorted(computed["source_to_avenues"].get(source_id, []))
            states = sorted(computed["source_to_states"].get(source_id, set()))
            writer.writerow(
                {
                    "source_id": source_id,
                    "family": status.get("family", ""),
                    "pipeline_status": status.get("pipeline_status", ""),
                    "guide_relation": "INTERSECTION" if avenues else "B_ONLY",
                    "guide_avenue_ids": ";".join(avenues),
                    "binding_states": ";".join(states),
                }
            )

    canonical = validated["canonical_by_id"]
    mapping = inputs["bindings"]["bindings"]
    proposed = inputs["bindings"].get("proposed_overlay_bindings") or {}
    with avenue_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "avenue_id",
            "canonical",
            "binding_state",
            "base_source_ids",
            "proposed_overlay_source_ids",
            "set_relation",
            "certification_state",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for avenue_id in validated["avenue_ids"]:
            binding = mapping[avenue_id]
            represented = binding["state"] != "ABSENT"
            writer.writerow(
                {
                    "avenue_id": avenue_id,
                    "canonical": canonical[avenue_id],
                    "binding_state": binding["state"],
                    "base_source_ids": ";".join(binding.get("source_ids") or []),
                    "proposed_overlay_source_ids": ";".join(proposed.get(avenue_id) or []),
                    "set_relation": "INTERSECTION" if represented else "A_ONLY",
                    "certification_state": "OPEN",
                }
            )

    payload = metrics_payload(inputs, validated, computed)
    metrics_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {
        "source_audit": str(source_path),
        "avenue_audit": str(avenue_path),
        "metrics": str(metrics_path),
        "metrics_payload": payload,
    }


def run(root: Path = PROJECT_ROOT, *, write: bool = True) -> dict:
    inputs = load_inputs(root)
    validated = validate_inputs(inputs)
    computed = compute(inputs, validated)
    result = {
        "inputs": inputs,
        "validated": validated,
        "computed": computed,
        "metrics_payload": metrics_payload(inputs, validated, computed),
    }
    if write:
        result["outputs"] = write_outputs(root, inputs, validated, computed)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate/compute without writing reports"
    )
    args = parser.parse_args()
    result = run(write=not args.check)
    print(json.dumps(result["metrics_payload"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
