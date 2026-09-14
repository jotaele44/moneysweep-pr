from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

EXPECTED_COLUMNS = {
    "source_id",
    "required",
    "family",
    "update_cadence",
    "authentication",
    "required_secret",
    "trigger_type",
    "terminal",
    "path_type",
    "automatable",
    "ready",
    "needs_key",
    "has_adapter",
    "producer_importable",
    "producer_script",
    "expected_outputs_count",
    "outputs_present_count",
    "min_rows",
    "dropzone_path",
    "recommended_action",
}
TRANCHE_ORDER = (
    "keyless_schedule",
    "keyless_dependency",
    "keyless_other",
    "credential_gated",
)


def _bool(value: str) -> bool:
    return value.strip().lower() == "true"


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = sorted(EXPECTED_COLUMNS - set(reader.fieldnames or []))
        if missing:
            raise RuntimeError("source recovery matrix missing columns: " + ", ".join(missing))
        rows = list(reader)
    ids = [row["source_id"] for row in rows]
    if any(not source_id or source_id != source_id.strip() for source_id in ids):
        raise RuntimeError("source recovery matrix contains blank/noncanonical source_id")
    duplicates = sorted(source_id for source_id, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise RuntimeError("duplicate source IDs: " + ", ".join(duplicates))
    return rows


def _entry(row: dict[str, str]) -> dict[str, Any]:
    return {
        "source_id": row["source_id"],
        "required": _bool(row["required"]),
        "family": row["family"],
        "trigger_type": row["trigger_type"],
        "path_type": row["path_type"],
        "producer_script": row["producer_script"],
        "needs_key": row["needs_key"] or None,
        "expected_outputs_count": int(row["expected_outputs_count"] or 0),
        "outputs_present_count": int(row["outputs_present_count"] or 0),
        "min_rows": int(row["min_rows"] or 0),
    }


def build(path: Path) -> dict[str, Any]:
    rows = _read_rows(path)
    automatable = [row for row in rows if _bool(row["automatable"])]
    excluded = [row for row in rows if not _bool(row["automatable"])]
    not_ready = [row["source_id"] for row in automatable if not _bool(row["ready"])]
    if not_ready:
        raise RuntimeError("automatable sources not ready: " + ", ".join(sorted(not_ready)))

    keyed = [row for row in automatable if row["needs_key"].strip()]
    keyless = [row for row in automatable if not row["needs_key"].strip()]
    tranches: dict[str, list[dict[str, Any]]] = {name: [] for name in TRANCHE_ORDER}

    for row in keyless:
        trigger = row["trigger_type"].strip()
        tranche = (
            "keyless_schedule"
            if trigger == "schedule"
            else "keyless_dependency"
            if trigger == "dependency"
            else "keyless_other"
        )
        tranches[tranche].append(_entry(row))
    for row in keyed:
        tranches["credential_gated"].append(_entry(row))
    for values in tranches.values():
        values.sort(key=lambda item: item["source_id"])

    total = len(rows)
    automatable_total = len(automatable)
    excluded_total = len(excluded)
    keyless_total = len(keyless)
    keyed_total = len(keyed)
    if automatable_total + excluded_total != total:
        raise RuntimeError("population arithmetic does not close")
    if keyless_total + keyed_total != automatable_total:
        raise RuntimeError("automatable partition arithmetic does not close")

    output_presence: Counter[str] = Counter()
    for row in automatable:
        expected = int(row["expected_outputs_count"] or 0)
        present = int(row["outputs_present_count"] or 0)
        if present > expected:
            raise RuntimeError(
                f'{row["source_id"]}: outputs_present_count exceeds expected_outputs_count'
            )
        state = (
            "NO_DECLARED_OUTPUTS"
            if expected == 0
            else "ALL_PRESENT"
            if present == expected
            else "NONE_PRESENT"
            if present == 0
            else "PARTIAL_PRESENT"
        )
        output_presence[state] += 1

    return {
        "schema_version": "moneysweep.automatable_execution_plan/v1",
        "source_matrix": path.as_posix(),
        "population": {
            "total_sources": total,
            "automatable_total": automatable_total,
            "excluded_total": excluded_total,
            "keyless_total": keyless_total,
            "credential_gated_total": keyed_total,
            "arithmetic": {
                "automatable_plus_excluded": automatable_total + excluded_total,
                "keyless_plus_credential_gated": keyless_total + keyed_total,
            },
        },
        "required_keys": sorted({row["needs_key"].strip() for row in keyed}),
        "required_automatable_source_ids": sorted(
            row["source_id"] for row in automatable if _bool(row["required"])
        ),
        "output_presence_counts": dict(sorted(output_presence.items())),
        "tranches": tranches,
        "policy": {
            "runner_startup_bypass_does_not_waive_execution_evidence": True,
            "missing_credentials_do_not_block_keyless_tranches": True,
            "dependency_tranches_run_after_their_upstreams": True,
            "success_requires_declared_outputs_and_source_bound_receipts": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("reports/source_recovery_matrix.csv"),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("reports/automatable_execution_plan.json"),
    )
    args = parser.parse_args()
    report = build(args.matrix)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report["population"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
