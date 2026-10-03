from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from tools.operator_corpus_common import load_sources

SCHEMA_VERSION = "moneysweep.coverage_contract_backlog/v1"


def _bool(value: object) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _name_only(fields: list[str]) -> bool:
    if not fields:
        return False
    tokens = [field.casefold().replace("-", "_") for field in fields]
    return all(
        token in {"name", "normalized_name", "canonical_name"}
        or token.endswith("_name")
        or token.startswith("name_")
        for token in tokens
    )


def _load_recovery(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_contracts(path: Path) -> list[dict[str, Any]]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise RuntimeError("coverage contracts must be a YAML mapping")
    if payload.get("schema_version") != "coverage_contracts_v1":
        raise RuntimeError("coverage contract schema_version mismatch")
    contracts = payload.get("contracts")
    if not isinstance(contracts, list):
        raise RuntimeError("coverage contracts must contain contracts[]")
    if any(not isinstance(item, dict) for item in contracts):
        raise RuntimeError("coverage contracts contain non-object row")
    return contracts


def build(
    *,
    root: Path,
    recovery_path: Path | None = None,
    contracts_path: Path | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    recovery_path = recovery_path or root / "reports/source_recovery_matrix.csv"
    contracts_path = contracts_path or root / "registries/coverage_contracts.yaml"

    sources, _ = load_sources(root)
    registry_ids = [str(source["source_id"]) for source in sources]
    registry_set = set(registry_ids)
    if len(registry_ids) != len(registry_set):
        raise RuntimeError("registry contains duplicate source IDs")

    recovery = _load_recovery(recovery_path)
    recovery_ids = [str(row.get("source_id") or "") for row in recovery]
    if any(not source_id for source_id in recovery_ids):
        raise RuntimeError("recovery matrix contains blank source_id")
    recovery_counts = Counter(recovery_ids)
    recovery_duplicates = sorted(
        source_id for source_id, count in recovery_counts.items() if count > 1
    )
    recovery_missing = sorted(registry_set - set(recovery_ids))
    recovery_unknown = sorted(set(recovery_ids) - registry_set)
    if recovery_duplicates or recovery_missing or recovery_unknown:
        raise RuntimeError(
            "recovery matrix identity mismatch: "
            f"duplicates={recovery_duplicates}; "
            f"missing={recovery_missing}; unknown={recovery_unknown}"
        )

    contracts = _load_contracts(contracts_path)
    contract_ids = [str(item.get("source_id") or "") for item in contracts]
    if any(not source_id for source_id in contract_ids):
        raise RuntimeError("coverage contract contains blank source_id")
    contract_counts = Counter(contract_ids)
    contract_duplicates = sorted(
        source_id for source_id, count in contract_counts.items() if count > 1
    )
    contract_unknown = sorted(set(contract_ids) - registry_set)
    if contract_duplicates or contract_unknown:
        raise RuntimeError(
            "coverage contract identity mismatch: "
            f"duplicates={contract_duplicates}; unknown={contract_unknown}"
        )

    contract_by_id = {str(item["source_id"]): item for item in contracts}
    recovery_by_id = {str(row["source_id"]): row for row in recovery}

    rows: list[dict[str, Any]] = []
    for source_id in sorted(registry_set):
        recovery_row = recovery_by_id[source_id]
        automatable = _bool(recovery_row.get("automatable"))
        contract = contract_by_id.get(source_id)

        blockers: list[str] = []
        if contract is None:
            state = "CONTRACT_MISSING"
            blockers.append("coverage_contract_missing")
            universe_method = None
            universe_ref = None
            universe_total = None
            uniqueness_key: list[str] = []
            pagination_required = None
        else:
            universe_method = contract.get("authoritative_universe_method")
            universe_ref = contract.get("authoritative_universe_ref")
            universe_total = contract.get("authoritative_universe_total")
            raw_key = contract.get("uniqueness_key")
            uniqueness_key = (
                [str(item) for item in raw_key]
                if isinstance(raw_key, list)
                else []
            )
            pagination_required = bool(contract.get("pagination_required", False))

            if not uniqueness_key:
                blockers.append("identity_key_missing")
            elif _name_only(uniqueness_key):
                blockers.append("identity_key_name_only")
            if universe_total is None:
                blockers.append("authoritative_denominator_unmeasured")
            elif isinstance(universe_total, bool) or not isinstance(
                universe_total, (int, float)
            ):
                blockers.append("authoritative_denominator_invalid")
            elif universe_total < 0:
                blockers.append("authoritative_denominator_invalid")

            if "identity_key_missing" in blockers:
                state = "IDENTITY_KEY_MISSING"
            elif "identity_key_name_only" in blockers:
                state = "IDENTITY_KEY_NAME_ONLY"
            elif any(
                blocker.startswith("authoritative_denominator")
                for blocker in blockers
            ):
                state = "DENOMINATOR_UNMEASURED"
            else:
                state = "CONTRACT_STRUCTURALLY_READY"

        rows.append(
            {
                "source_id": source_id,
                "required": _bool(recovery_row.get("required")),
                "automatable": automatable,
                "path_type": recovery_row.get("path_type"),
                "authentication": recovery_row.get("authentication"),
                "contract_state": state,
                "contract_version": (
                    contract.get("contract_version") if contract is not None else None
                ),
                "authoritative_universe_method": universe_method,
                "authoritative_universe_ref": universe_ref,
                "authoritative_universe_total": universe_total,
                "uniqueness_key": uniqueness_key,
                "pagination_required": pagination_required,
                "blockers": sorted(set(blockers)),
            }
        )

    automatable_rows = [row for row in rows if row["automatable"]]
    automatable_state_counts = Counter(
        row["contract_state"] for row in automatable_rows
    )
    required_rows = [row for row in rows if row["required"]]
    required_state_counts = Counter(row["contract_state"] for row in required_rows)

    automatable_blockers = [
        row for row in automatable_rows
        if row["contract_state"] != "CONTRACT_STRUCTURALLY_READY"
    ]
    required_blockers = [
        row for row in required_rows
        if row["contract_state"] != "CONTRACT_STRUCTURALLY_READY"
    ]

    summary = {
        "registry_total": len(rows),
        "recovery_total": len(recovery),
        "contract_total": len(contracts),
        "automatable_total": len(automatable_rows),
        "required_total": len(required_rows),
        "automatable_state_counts": dict(sorted(automatable_state_counts.items())),
        "required_state_counts": dict(sorted(required_state_counts.items())),
        "automatable_blocker_total": len(automatable_blockers),
        "required_blocker_total": len(required_blockers),
        "automatable_structurally_ready_total": automatable_state_counts.get(
            "CONTRACT_STRUCTURALLY_READY", 0
        ),
    }

    if summary["registry_total"] != summary["recovery_total"]:
        raise RuntimeError("registry/recovery arithmetic does not close")
    if sum(summary["automatable_state_counts"].values()) != summary["automatable_total"]:
        raise RuntimeError("automatable contract-state arithmetic does not close")
    if sum(summary["required_state_counts"].values()) != summary["required_total"]:
        raise RuntimeError("required contract-state arithmetic does not close")

    return {
        "schema_version": SCHEMA_VERSION,
        "claim": (
            "Contract structural readiness only; this report does not establish "
            "materialization, coverage completeness, freshness, or certification."
        ),
        "summary": summary,
        "automatable_blocker_ids": [
            row["source_id"] for row in automatable_blockers
        ],
        "required_blocker_ids": [row["source_id"] for row in required_blockers],
        "sources": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the exact coverage-contract structural backlog."
    )
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--recovery",
        type=Path,
        help="Optional source recovery matrix override.",
    )
    parser.add_argument(
        "--contracts",
        type=Path,
        help="Optional coverage contracts YAML override.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/coverage_contract_backlog.json"),
    )
    args = parser.parse_args()

    report = build(
        root=args.root,
        recovery_path=args.recovery,
        contracts_path=args.contracts,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
