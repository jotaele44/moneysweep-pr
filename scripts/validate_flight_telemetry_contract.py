#!/usr/bin/env python3
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / ".federation" / "flight_telemetry_contract.json"
BINDING_PATH = ROOT / ".federation" / "flight_telemetry_binding.json"
EXPECTED_ID = "flight-telemetry-contract/1.0"
EXPECTED_SCHEMA_VERSION = "1.0.0"
EXPECTED_REQUIRED = ["source", "timestamp_utc", "latitude", "longitude"]
EXPECTED_SHA256 = "15d13c9c625ac1318589b3a4aae0c9f0c776e06b439a98c733d50ed90a849506"
EXPECTED_UNITS = {
    "timestamp_utc": "ISO-8601 UTC",
    "latitude": "decimal_degrees",
    "longitude": "decimal_degrees",
    "baro_altitude_ft": "feet",
    "geometric_altitude_ft": "feet",
    "groundspeed_kt": "knots",
    "track_deg": "degrees_true",
    "vertical_rate_fpm": "feet_per_minute",
}
BREAKING = {
    "removing_or_renaming_field": "breaking",
    "changing_units": "breaking",
    "changing_null_semantics": "breaking",
    "adding_required_field": "breaking",
    "adding_optional_field": "additive",
}


def fail(msg):
    raise SystemExit(msg)


def validate_contract(obj, enforce_hash=False):
    if obj.get("$id") != EXPECTED_ID:
        fail("contract id mismatch")
    if obj.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        fail("schema version mismatch")
    if obj.get("required") != EXPECTED_REQUIRED:
        fail("required fields changed")
    if obj.get("units") != EXPECTED_UNITS:
        fail("unit semantics changed")
    if obj.get("compatibility") != BREAKING:
        fail("breaking-change policy changed")
    if (
        obj.get("null_semantics", {}).get("optional_fields")
        != "null means source did not provide or value was not available; null never means zero"
    ):
        fail("null semantics changed")
    must = {
        "source manifestation is preserved",
        "normalization does not establish source identity",
        "duplicate adjudication preserves full candidate sets",
        "tied top evidence remains UNRESOLVED",
        "join cardinality is reported",
        "proximity alone never establishes operational relationship or mission purpose",
    }
    missing = must - set(obj.get("invariants", []))
    if missing:
        fail(f"missing invariants: {sorted(missing)}")
    if enforce_hash and hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() != EXPECTED_SHA256:
        fail("contract byte hash mismatch")


def validate_binding(binding):
    if binding.get("contract_id") != EXPECTED_ID:
        fail("binding contract mismatch")
    if binding.get("strict_parallel_development") is not True:
        fail("strict parallel development disabled")
    if binding.get("breaking_change_policy") != "FAIL_CLOSED":
        fail("breaking-change policy must fail closed")
    if not binding.get("repo") or not binding.get("role"):
        fail("repo/role missing")
    if not isinstance(binding.get("declared_downstream_or_peer_consumers"), list):
        fail("consumer list missing")


def negative_regression(base):
    cases = []
    x = copy.deepcopy(base)
    x["units"]["latitude"] = "radians"
    cases.append(("unit_change", x))
    x = copy.deepcopy(base)
    x["required"].append("registration")
    cases.append(("new_required", x))
    x = copy.deepcopy(base)
    x["null_semantics"]["optional_fields"] = "null means zero"
    cases.append(("null_change", x))
    x = copy.deepcopy(base)
    x["invariants"].remove("tied top evidence remains UNRESOLVED")
    cases.append(("tie_rule_removed", x))
    x = copy.deepcopy(base)
    x["compatibility"]["adding_required_field"] = "additive"
    cases.append(("policy_weakened", x))
    for name, mutated in cases:
        try:
            validate_contract(mutated)
        except SystemExit:
            continue
        fail(f"negative regression failed: {name} accepted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--negative-regression", action="store_true")
    args = ap.parse_args()
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    binding = json.loads(BINDING_PATH.read_text(encoding="utf-8"))
    validate_contract(contract, enforce_hash=True)
    validate_binding(binding)
    if args.negative_regression:
        negative_regression(contract)
    print(
        json.dumps(
            {
                "state": "PASS",
                "contract_id": EXPECTED_ID,
                "repo": binding["repo"],
                "role": binding["role"],
                "negative_regression": "PASS" if args.negative_regression else "NOT_RUN",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
