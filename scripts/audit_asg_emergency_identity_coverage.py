#!/usr/bin/env python3
"""Audit ASG emergency-purchase identity and financial-value readiness.

This script does not rank vendors. It evaluates the materialized source against
MoneySweep's fail-closed leaderboard prerequisites:
- control_number uniqueness;
- source-native ASG Licitador ID presence;
- no promotion of name-only identities;
- parseable purchase-order cost;
- a measured current coverage denominator.

The output is an adjudication receipt used to decide whether a future
ASG-emergency leaderboard adapter may be promoted into the ontology.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "staging" / "processed" / "pr_asg_emergency_purchases.csv"
DEFAULT_COVERAGE = ROOT / "registries" / "coverage_contracts.json"
DEFAULT_OUTPUT = (
    ROOT
    / "data"
    / "manifests"
    / "asg_emergency_purchases"
    / "identity_coverage_latest.json"
)

SOURCE_NATIVE = "SOURCE_NATIVE_ASG_LICITADOR_ID"
_AMOUNT_RE = re.compile(r"[^0-9.\-]+")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _amount(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    cleaned = _AMOUNT_RE.sub("", text.replace(",", ""))
    if cleaned in {"", "-", ".", "-."}:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _coverage_contract(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return next(
        (item for item in data.get("contracts") or [] if item.get("source_id") == "asg_emergency_purchases"),
        None,
    )


def audit(input_path: Path, coverage_path: Path) -> dict[str, Any]:
    if not input_path.exists():
        return {
            "schemaVersion": "moneysweep.asg-emergency-identity-coverage/v1",
            "state": "OPEN_NOT_MATERIALIZED",
            "sourcePath": str(input_path.relative_to(ROOT)) if input_path.is_relative_to(ROOT) else str(input_path),
            "leaderboardPromotionReady": False,
            "blockingResidue": ["SOURCE_NOT_MATERIALIZED"],
        }

    rows = list(csv.DictReader(input_path.open(newline="", encoding="utf-8")))
    required = {
        "control_number",
        "vendor_name",
        "vendor_registration_id",
        "vendor_identity_state",
        "obligation_amount",
    }
    missing_columns = sorted(required - set(rows[0].keys() if rows else []))

    control_numbers = [str(row.get("control_number") or "").strip() for row in rows]
    duplicates = len(control_numbers) - len(set(control_numbers))
    source_native = 0
    name_only = 0
    missing_vendor = 0
    valid_amount = 0
    invalid_amount = 0
    candidate_rows = 0
    candidate_total = 0.0

    for row in rows:
        state = str(row.get("vendor_identity_state") or "").strip()
        registration_id = str(row.get("vendor_registration_id") or "").strip()
        vendor_name = str(row.get("vendor_name") or "").strip()
        amount = _amount(row.get("obligation_amount"))

        if state == SOURCE_NATIVE and registration_id:
            source_native += 1
        elif vendor_name:
            name_only += 1
        else:
            missing_vendor += 1

        if amount is None:
            invalid_amount += 1
        else:
            valid_amount += 1

        if state == SOURCE_NATIVE and registration_id and amount is not None:
            candidate_rows += 1
            candidate_total += amount

    contract = _coverage_contract(coverage_path)
    universe_total = None if contract is None else contract.get("authoritative_universe_total")
    if universe_total is None:
        coverage_state = "UNVERIFIABLE_DENOMINATOR"
        coverage_pct = None
    elif universe_total <= 0:
        coverage_state = "INVALID_DENOMINATOR"
        coverage_pct = None
    else:
        coverage_pct = 100.0 * len(set(control_numbers)) / float(universe_total)
        floor = float(contract.get("minimum_coverage_pct") or 100.0)
        coverage_state = "MEETS_CONTRACT" if coverage_pct >= floor else "BELOW_CONTRACT"

    blockers: list[str] = []
    if missing_columns:
        blockers.append("MISSING_REQUIRED_COLUMNS")
    if duplicates:
        blockers.append("DUPLICATE_CONTROL_NUMBER")
    if universe_total is None:
        blockers.append("CURRENT_DENOMINATOR_UNMEASURED")
    if name_only:
        blockers.append("NAME_ONLY_VENDOR_IDENTITY_RESIDUE")
    if missing_vendor:
        blockers.append("MISSING_VENDOR_IDENTITY_RESIDUE")
    if invalid_amount:
        blockers.append("INVALID_AMOUNT_RESIDUE")
    if not candidate_rows:
        blockers.append("NO_SOURCE_NATIVE_AMOUNT_ROWS")

    result = {
        "schemaVersion": "moneysweep.asg-emergency-identity-coverage/v1",
        "state": "PASS" if not blockers else "OPEN",
        "sourcePath": str(input_path.relative_to(ROOT)) if input_path.is_relative_to(ROOT) else str(input_path),
        "sourceSha256": _sha256(input_path),
        "inputRecords": len(rows),
        "uniqueControlNumbers": len(set(control_numbers)),
        "duplicateControlNumbers": duplicates,
        "identity": {
            "sourceNativeRows": source_native,
            "nameOnlyRows": name_only,
            "missingVendorRows": missing_vendor,
            "identityScheme": "asg_licitador_id",
            "nameOnlyPromotionAllowed": False,
        },
        "financialValue": {
            "validAmountRows": valid_amount,
            "invalidAmountRows": invalid_amount,
            "candidateRows": candidate_rows,
            "candidateAmountTotal": round(candidate_total, 2),
            "measure": "ASG_EMERGENCY_PURCHASE_COST",
            "currency": "USD",
        },
        "coverage": {
            "state": coverage_state,
            "authoritativeUniverseTotal": universe_total,
            "coveragePct": coverage_pct,
        },
        "missingRequiredColumns": missing_columns,
        "blockingResidue": blockers,
        "leaderboardPromotionReady": not blockers,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--coverage", type=Path, default=DEFAULT_COVERAGE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    result = audit(args.input.resolve(), args.coverage.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("leaderboardPromotionReady") else 1


if __name__ == "__main__":
    raise SystemExit(main())
