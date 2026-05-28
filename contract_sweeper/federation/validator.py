"""Fail-closed validation for federation export packages.

Pure Python — deliberately independent of ``jsonschema``. The repo's existing
``SchemaValidator`` no-ops (returns valid=True) when ``jsonschema`` is not
installed, which is unsafe for a gate that must FAIL CLOSED before a record is
admitted to the federation hub. These checks always run and an empty package is
treated as invalid.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Sequence, Union

from .namespace import PREFIX

REQUIRED_KEYS = (
    "producer",
    "record_type",
    "record_id",
    "source_id",
    "timestamp",
    "geo",
    "entities",
    "confidence",
    "lineage",
    "payload",
    "synthetic",
)

# Record types that must additionally pass the financial gate.
FINANCIAL_RECORD_TYPES = frozenset({"funding_award", "transaction"})

_CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def _is_iso8601(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    # datetime.fromisoformat() rejects a trailing 'Z' before Python 3.11.
    candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(candidate)
        return True
    except ValueError:
        return False


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_envelope(record: Any, *, expected_prefix: str = PREFIX) -> List[str]:
    """Return a list of error strings; empty means the envelope is valid."""
    if not isinstance(record, dict):
        return ["record is not an object"]

    errors: List[str] = []
    missing = [k for k in REQUIRED_KEYS if k not in record]
    if missing:
        # Without the required keys we cannot safely inspect further.
        return [f"missing key: {k}" for k in missing]

    if not isinstance(record["producer"], str) or not record["producer"]:
        errors.append("producer must be a non-empty string")
    if not isinstance(record["record_type"], str) or not record["record_type"]:
        errors.append("record_type must be a non-empty string")

    token = f"{expected_prefix}:"
    for id_key in ("record_id", "source_id"):
        value = record[id_key]
        if not isinstance(value, str) or not value:
            errors.append(f"{id_key} must be a non-empty string")
        elif not value.startswith(token):
            errors.append(f"{id_key} must be namespaced with '{token}' (got {value!r})")

    ts = record["timestamp"]
    if ts is not None and not _is_iso8601(ts):
        errors.append(f"timestamp must be ISO-8601 or null (got {ts!r})")

    geo = record["geo"]
    if geo is not None and (not isinstance(geo, dict) or "type" not in geo or "coordinates" not in geo):
        errors.append("geo must be null or an object with 'type' and 'coordinates'")

    entities = record["entities"]
    if not isinstance(entities, list):
        errors.append("entities must be a list")
    else:
        for i, ent in enumerate(entities):
            if not isinstance(ent, dict) or not all(
                k in ent for k in ("entity_id", "name", "normalized_name")
            ):
                errors.append(f"entities[{i}] must have entity_id, name, normalized_name")

    conf = record["confidence"]
    if not isinstance(conf, dict) or "score" not in conf or "method" not in conf:
        errors.append("confidence must be an object with 'score' and 'method'")
    else:
        score = conf["score"]
        if not _is_number(score) or not (0.0 <= float(score) <= 1.0):
            errors.append(f"confidence.score must be a number in [0,1] (got {score!r})")
        if not isinstance(conf["method"], str) or not conf["method"]:
            errors.append("confidence.method must be a non-empty string")

    if not isinstance(record["lineage"], list):
        errors.append("lineage must be a list")
    if not isinstance(record["payload"], dict):
        errors.append("payload must be an object")
    if not isinstance(record["synthetic"], bool):
        errors.append("synthetic must be a boolean")

    return errors


def validate_financial(record: Any) -> List[str]:
    """Financial gate for funding_award / transaction records.

    Requires a numeric non-negative ``payload.amount``, an ISO-4217
    ``payload.currency``, and a non-empty top-level ``lineage``.
    """
    if not isinstance(record, dict) or record.get("record_type") not in FINANCIAL_RECORD_TYPES:
        return []

    errors: List[str] = []
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return ["financial record payload must be an object"]

    amount = payload.get("amount")
    if not _is_number(amount) or float(amount) < 0:
        errors.append(f"financial record requires numeric payload.amount >= 0 (got {amount!r})")

    currency = payload.get("currency")
    if not isinstance(currency, str) or not _CURRENCY_RE.match(currency):
        errors.append(f"financial record requires ISO-4217 payload.currency (got {currency!r})")

    if not record.get("lineage"):
        errors.append("financial record requires non-empty lineage")

    return errors


StreamsInput = Union[Mapping[str, Sequence[Dict[str, Any]]], Sequence[Dict[str, Any]]]


def _flatten(streams: StreamsInput):
    """Yield (stream_name, index, record) across a multi-stream package."""
    if isinstance(streams, Mapping):
        for name, rows in streams.items():
            for i, rec in enumerate(rows or []):
                yield name, i, rec
    else:
        for i, rec in enumerate(streams or []):
            yield "(rows)", i, rec


def _entity_ids(streams: StreamsInput) -> set:
    ids = set()
    for _name, _i, rec in _flatten(streams):
        if isinstance(rec, dict) and rec.get("record_type") == "entity":
            rid = rec.get("record_id")
            if isinstance(rid, str):
                ids.add(rid)
    return ids


def validate_package(
    streams: StreamsInput,
    *,
    expected_prefix: str = PREFIX,
    require_financial: bool = True,
    reject_synthetic: bool = False,
) -> Dict[str, Any]:
    """Validate a whole export package. Fail-closed.

    ``streams`` may be a mapping of stream-name -> records or a flat sequence.
    An empty package is INVALID (guards against the silent no-op trap).
    Relationship records must reference entity IDs present in the package.
    """
    rows = list(_flatten(streams))
    if not rows:
        return {"valid": False, "errors": ["package is empty (fail-closed)"], "count": 0}

    entity_ids = _entity_ids(streams)
    errors: List[str] = []

    for name, i, rec in rows:
        loc = f"{name}[{i}]"
        for err in validate_envelope(rec, expected_prefix=expected_prefix):
            errors.append(f"{loc}: {err}")
        if require_financial:
            for err in validate_financial(rec):
                errors.append(f"{loc}: {err}")
        if reject_synthetic and isinstance(rec, dict) and rec.get("synthetic") is True:
            errors.append(f"{loc}: synthetic record rejected in production mode")
        if isinstance(rec, dict) and rec.get("record_type") == "relationship":
            for ref in rec.get("entities") or []:
                if isinstance(ref, dict):
                    ref_id = ref.get("entity_id")
                    if entity_ids and ref_id not in entity_ids:
                        errors.append(f"{loc}: relationship references unknown entity_id {ref_id!r}")

    return {"valid": len(errors) == 0, "errors": errors, "count": len(rows)}
