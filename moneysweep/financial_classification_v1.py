"""Additive, source-preserving financial observations (Issue #695).

No legacy stream or identifier is modified. This module does not assert
completeness of any financial source; that requires a separately frozen manifest.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from typing import Mapping

MEASURES = frozenset(
    {
        "APPROPRIATED",
        "APPORTIONED",
        "ALLOTTED",
        "OBLIGATED",
        "DEOBLIGATED",
        "UNOBLIGATED",
        "DISBURSED",
        "UNDISBURSED",
        "OUTLAY",
        "EXPENDED",
        "TRANSFERRED",
        "REPROGRAMMED",
        "RESCINDED",
        "REMAINING_AVAILABLE",
    }
)
EVIDENCE_CLASSES = frozenset(
    {
        "FACT",
        "COMPUTED",
        "BINDING",
        "INFERENCE",
        "ASSUMPTION",
        "HYPOTHESIS",
        "UNKNOWN",
    }
)
APPLICABILITY = frozenset({"APPLICABLE", "NOT_APPLICABLE", "UNKNOWN", "UNRESOLVED"})
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_./:-]+$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ObservationError(ValueError):
    """A failed source, basis, identity, or arithmetic gate."""


def canonical_bytes(data: Mapping) -> bytes:
    return json.dumps(
        data, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def decimal_string(value: object) -> str:
    if isinstance(value, bool) or value is None or isinstance(value, float):
        raise ObservationError("amount must be an exact decimal string or integer")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ObservationError("invalid decimal amount") from exc
    if not amount.is_finite():
        raise ObservationError("nonfinite amount")
    return format(amount, "f")


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ObservationError(f"missing {field}")
    return value


def make_observation(
    *,
    source_id: str,
    source_record_id: str,
    source_sha256: str,
    measure_type: str,
    amount: str | int | None,
    currency: str,
    period: str,
    accounting_basis: str,
    scope_id: str,
    source_field: str,
    evidence_class: str = "FACT",
    applicability: str = "APPLICABLE",
    observation_kind: str = "SNAPSHOT",
    source_version: str = "1",
) -> dict:
    """Build one observation only from an explicit source-row mapping.

    No entity is bound by name; scope_id is a source-native scoped identifier.
    Source record identities and raw SHA are mandatory, including for UNKNOWN.
    """
    for key, value in {
        "source_id": source_id,
        "source_record_id": source_record_id,
        "period": period,
        "accounting_basis": accounting_basis,
        "scope_id": scope_id,
        "source_field": source_field,
        "source_version": source_version,
    }.items():
        _nonempty(value, key)
    if not SHA_PATTERN.fullmatch(source_sha256):
        raise ObservationError("source_sha256 must be lowercase SHA256")
    if measure_type not in MEASURES:
        raise ObservationError("unknown measure")
    if evidence_class not in EVIDENCE_CLASSES or applicability not in APPLICABILITY:
        raise ObservationError("invalid evidence or applicability class")
    if observation_kind not in {"SNAPSHOT", "PERIOD_FLOW", "ACTION"}:
        raise ObservationError("invalid observation kind")
    if not re.fullmatch(r"[A-Z]{3}", currency):
        raise ObservationError("invalid currency")
    if amount is not None and applicability != "APPLICABLE":
        raise ObservationError("non-applicable or unresolved row cannot carry an amount")
    if amount is None and evidence_class == "COMPUTED":
        raise ObservationError("computed amount is absent")
    amount_decimal = decimal_string(amount) if amount is not None else None
    payload = {
        "source_id": source_id,
        "source_record_id": source_record_id,
        "source_sha256": source_sha256,
        "source_version": source_version,
        "source_field": source_field,
        "measure_type": measure_type,
        "amount_decimal": amount_decimal,
        "currency": currency,
        "period": period,
        "accounting_basis": accounting_basis,
        "scope_id": scope_id,
        "evidence_class": evidence_class,
        "applicability": applicability,
        "observation_kind": observation_kind,
    }
    payload["observation_id"] = "finobs_" + hashlib.sha256(canonical_bytes(payload)).hexdigest()
    return payload


def undisbursed(obligated: Mapping, disbursed: Mapping) -> dict:
    """Derive only comparable cumulative snapshots; otherwise fail closed."""
    for observation, expected in ((obligated, "OBLIGATED"), (disbursed, "DISBURSED")):
        if observation.get("measure_type") != expected:
            raise ObservationError("incorrect measure pair")
        if observation.get("observation_kind") != "SNAPSHOT":
            raise ObservationError("period flows cannot yield a stock balance")
        if observation.get("applicability") != "APPLICABLE":
            raise ObservationError("unresolved applicability")
        if observation.get("amount_decimal") is None:
            raise ObservationError("missing amount")
    keys = (
        "source_id",
        "scope_id",
        "period",
        "accounting_basis",
        "currency",
        "source_sha256",
        "source_version",
    )
    if any(obligated.get(k) != disbursed.get(k) for k in keys):
        raise ObservationError("incompatible scope, source, period or basis")
    if obligated.get("source_record_id") != disbursed.get("source_record_id"):
        raise ObservationError("different source rows: no binding established")
    value = Decimal(obligated["amount_decimal"]) - Decimal(disbursed["amount_decimal"])
    if value < 0:
        raise ObservationError("negative balance requires adjudication")
    return make_observation(
        source_id=obligated["source_id"],
        source_record_id=obligated["source_record_id"],
        source_sha256=obligated["source_sha256"],
        source_version=obligated["source_version"],
        measure_type="UNDISBURSED",
        amount=format(value, "f"),
        currency=obligated["currency"],
        period=obligated["period"],
        accounting_basis=obligated["accounting_basis"],
        scope_id=obligated["scope_id"],
        source_field="computed:obligated-disbursed",
        evidence_class="COMPUTED",
        observation_kind="SNAPSHOT",
    )


def classify_coverage(records: list[Mapping], expected_source_records: set[str]) -> dict:
    """Conserve a bounded source-row denominator; require unique, explicit states."""
    seen: set[str] = set()
    tally = {state: 0 for state in sorted(APPLICABILITY)}
    for record in records:
        row = _nonempty(record.get("source_record_id"), "source_record_id")
        if row in seen:
            raise ObservationError("duplicate source record")
        if row not in expected_source_records:
            raise ObservationError("unexpected source record")
        seen.add(row)
        state = record.get("applicability")
        if state not in APPLICABILITY:
            raise ObservationError("missing applicability decision")
        tally[state] += 1
    if seen != expected_source_records:
        raise ObservationError("missing source records")
    return {
        "total": len(seen),
        "states": tally,
        "complete": True,
        "unresolved": tally["UNKNOWN"] + tally["UNRESOLVED"],
    }
