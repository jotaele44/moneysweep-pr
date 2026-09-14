"""Derive restartable execution waves for the current keyless automatable population.

This is an execution planner, not execution evidence. It consumes the generated
source recovery matrix and never upgrades readiness/output-count observations
into source success.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

ALLOWED_TRIGGERS = {"schedule", "dependency", "manual", "on_drop"}


class PlanError(ValueError):
    pass


def _bool(value: str) -> bool:
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    raise PlanError(f"invalid_boolean:{value}")


def build(rows: list[dict[str, str]]) -> dict[str, Any]:
    ids = [str(r.get("source_id", "")).strip() for r in rows]
    if any(not sid for sid in ids) or len(ids) != len(set(ids)):
        raise PlanError("missing_or_duplicate_source_id")

    automatable = [r for r in rows if _bool(r.get("automatable", ""))]
    not_ready = [r["source_id"] for r in automatable if not _bool(r.get("ready", ""))]
    if not_ready:
        raise PlanError("automatable_not_ready:" + ",".join(sorted(not_ready)))

    keyed = [r for r in automatable if str(r.get("required_secret", "")).strip()]
    keyless = [r for r in automatable if not str(r.get("required_secret", "")).strip()]
    if len(automatable) != len(keyed) + len(keyless):
        raise PlanError("credential_partition_does_not_close")

    waves: dict[str, list[dict[str, Any]]] = {
        "W1_SCHEDULE_INDEPENDENT": [],
        "W2_OPERATOR_TRIGGERED": [],
        "W3_DEPENDENCY_GATED": [],
    }
    for row in keyless:
        trigger = str(row.get("trigger_type", "")).strip()
        if trigger not in ALLOWED_TRIGGERS:
            raise PlanError(f"unknown_trigger:{row['source_id']}:{trigger}")
        present = int(str(row.get("outputs_present_count", "0") or "0"))
        expected = int(str(row.get("expected_outputs_count", "0") or "0"))
        if present < 0 or expected < 0 or present > expected:
            raise PlanError(f"invalid_output_accounting:{row['source_id']}")
        item = {
            "source_id": row["source_id"],
            "required": _bool(row.get("required", "")),
            "producer_script": row.get("producer_script", ""),
            "trigger_type": trigger,
            "path_type": row.get("path_type", ""),
            "expected_outputs_count": expected,
            "reported_outputs_present_count": present,
            "reported_output_presence_is_execution_evidence": False,
        }
        if trigger == "schedule":
            waves["W1_SCHEDULE_INDEPENDENT"].append(item)
        elif trigger in {"manual", "on_drop"}:
            waves["W2_OPERATOR_TRIGGERED"].append(item)
        else:
            item["dependency_order_state"] = "UNRESOLVED_UNTIL_UPSTREAM_RECEIPTS_PASS"
            waves["W3_DEPENDENCY_GATED"].append(item)

    for values in waves.values():
        values.sort(key=lambda x: x["source_id"])
    wave_counts = {name: len(values) for name, values in waves.items()}
    if sum(wave_counts.values()) != len(keyless):
        raise PlanError("keyless_wave_arithmetic_does_not_close")

    key_counts = Counter(str(r.get("required_secret", "")).strip() for r in keyed)
    return {
        "schema_version": "moneysweep.keyless_execution_waves/v1",
        "state": "PLAN_ONLY",
        "production_eligible": False,
        "automatable_total": len(automatable),
        "keyless_total": len(keyless),
        "credential_gated_total": len(keyed),
        "wave_counts": wave_counts,
        "waves": waves,
        "credential_gated": [
            {
                "source_id": r["source_id"],
                "required_secret": str(r.get("required_secret", "")).strip(),
                "producer_script": r.get("producer_script", ""),
                "trigger_type": r.get("trigger_type", ""),
            }
            for r in sorted(keyed, key=lambda x: x["source_id"])
        ],
        "required_secret_counts": dict(sorted(key_counts.items())),
        "invariants": {
            "automatable_partition_closes": len(automatable) == len(keyless) + len(keyed),
            "keyless_wave_partition_closes": sum(wave_counts.values()) == len(keyless),
            "readiness_is_execution_evidence": False,
            "reported_output_presence_is_execution_evidence": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix", type=Path, default=Path("reports/source_recovery_matrix.csv"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.matrix.open("r", encoding="utf-8-sig", newline="") as fh:
        report = build(list(csv.DictReader(fh)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(json.dumps({
        "automatable_total": report["automatable_total"],
        "keyless_total": report["keyless_total"],
        "credential_gated_total": report["credential_gated_total"],
        "wave_counts": report["wave_counts"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
