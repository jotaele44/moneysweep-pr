"""Evidence-gated, read-only compatibility bridge for the legacy financial flow master.

The legacy flow_id is random and is used only as an identifier within a frozen
legacy manifestation. Authoritative source-native identity comes exclusively
from reviewed bindings. This module never writes legacy exports or certifies
source completeness.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Mapping

from moneysweep.financial_classification_v1 import (
    ObservationError,
    decimal_string,
    make_observation,
)

_BINDING_FIELDS = (
    "source_id",
    "source_record_id",
    "source_sha256",
    "source_field",
    "source_version",
    "scope_id",
    "measure_type",
    "period",
    "accounting_basis",
    "currency",
    "observation_kind",
    "source_amount",
    "expected_source_system",
    "expected_source_file",
    "expected_amount_type",
)


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ObservationError(f"missing or invalid {field}")
    return value


def adapt_legacy_flows(
    rows: Iterable[Mapping[str, object]],
    *,
    bindings: Mapping[str, Mapping[str, object]],
    expected_flow_ids: set[str],
) -> dict:
    """Classify a frozen legacy manifestation without inventing source identity.

    Every bound row requires independent source-native identification and a
    raw-byte SHA256. Unbound rows remain unresolved. A complete legacy row
    inventory is NOT evidence of source coverage or certification.
    """
    seen: set[str] = set()
    observation_ids: set[str] = set()
    observations: list[dict] = []
    unresolved: list[dict] = []
    for row in rows:
        flow_id = _required_text(row.get("flow_id"), "legacy flow_id")
        if flow_id in seen:
            raise ObservationError("duplicate legacy flow_id")
        if flow_id not in expected_flow_ids:
            raise ObservationError("unexpected legacy flow_id")
        seen.add(flow_id)
        bound = bindings.get(flow_id)
        if bound is None:
            unresolved.append({"legacy_flow_id": flow_id, "reason": "SOURCE_BINDING_UNVERIFIED"})
            continue
        if any(key not in bound for key in _BINDING_FIELDS):
            raise ObservationError("incomplete authoritative source binding")
        for key in ("source_system", "source_file", "amount_type"):
            expected = _required_text(bound.get(f"expected_{key}"), f"expected_{key}")
            if row.get(key) != expected:
                raise ObservationError(f"legacy row mismatch: {key}")
        original = decimal_string(row.get("amount"))
        source = decimal_string(bound["source_amount"])
        if Decimal(original) != Decimal(source):
            raise ObservationError("legacy amount differs from verified source amount")
        observed = make_observation(
            source_id=_required_text(bound["source_id"], "source_id"),
            source_record_id=_required_text(bound["source_record_id"], "source_record_id"),
            source_sha256=_required_text(bound["source_sha256"], "source_sha256"),
            source_field=_required_text(bound["source_field"], "source_field"),
            source_version=_required_text(bound["source_version"], "source_version"),
            scope_id=_required_text(bound["scope_id"], "scope_id"),
            measure_type=_required_text(bound["measure_type"], "measure_type"),
            period=_required_text(bound["period"], "period"),
            accounting_basis=_required_text(bound["accounting_basis"], "accounting_basis"),
            currency=_required_text(bound["currency"], "currency"),
            observation_kind=_required_text(bound["observation_kind"], "observation_kind"),
            amount=source,
        )
        if observed["observation_id"] in observation_ids:
            raise ObservationError("duplicate canonical observation in legacy manifestation")
        observation_ids.add(observed["observation_id"])
        observations.append({"legacy_flow_id": flow_id, "observation": observed})
    if seen != expected_flow_ids:
        raise ObservationError("missing legacy flow rows")
    if set(bindings) - seen:
        raise ObservationError("bindings reference unknown legacy rows")
    return {
        "legacy_rows": len(seen),
        "mapped": len(observations),
        "unresolved": len(unresolved),
        "observations": observations,
        "unresolved_rows": unresolved,
        "legacy_inventory_complete": True,
        "source_universe_certified": False,
        "promotion_authorized": False,
    }
