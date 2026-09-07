#!/usr/bin/env python3
"""Build MoneySweep -> federation spatial binding candidates without fabricating geometry.

Input JSONL rows are financial/project records. The adapter emits candidate bindings
only from explicit spatial evidence supplied on the source row. It never creates
coordinates, centroids, nearest-facility identities, or name-only identity bindings.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

FORBIDDEN_METHODS = {
    "NAME_ONLY",
    "NORMALIZED_NAME_ONLY",
    "COUNT_EQUALITY",
    "NEAREST_ONLY",
    "PROXIMITY_ONLY",
    "SAME_CATEGORY",
    "SOURCE_ABSENCE",
    "MUNICIPIO_CENTROID",
    "PIXEL_GRID",
    "PLACEHOLDER_COORDINATE",
}
ALLOWED_CARDINALITY = {"1:1", "1:N", "N:1", "N:N", "0:1", "UNRESOLVED"}


def adapt(row: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise ValueError("input row must be an object")
    raw_record_id = row.get("record_id")
    if raw_record_id is None:
        raw_record_id = row.get("project_id")
    if isinstance(raw_record_id, bool) or not isinstance(raw_record_id, (str, int)):
        raise ValueError("record_id/project_id must be a string or integer")
    record_id_raw = str(raw_record_id)
    record_id = record_id_raw.strip()
    if not record_id:
        raise ValueError("record_id/project_id is required")
    evidence = row.get("spatial_evidence")
    if evidence is None:
        evidence = []
    if not isinstance(evidence, list):
        raise ValueError(f"spatial_evidence must be an array for {record_id}")

    candidates: list[dict[str, Any]] = []
    seen_candidates: set[tuple[Any, ...]] = set()
    for index, item in enumerate(evidence):
        if not isinstance(item, Mapping):
            raise ValueError(f"spatial_evidence[{index}] must be an object for {record_id}")
        raw_method = item.get("method")
        if raw_method is None:
            method = "UNKNOWN"
        elif not isinstance(raw_method, str) or not raw_method.strip():
            raise ValueError(f"spatial_evidence[{index}].method must be non-empty")
        else:
            method = raw_method.strip().upper()

        canonical_id_raw = item.get("canonical_id")
        if canonical_id_raw is None:
            canonical_id = None
        elif not isinstance(canonical_id_raw, str) or not canonical_id_raw.strip():
            raise ValueError(
                f"spatial_evidence[{index}].canonical_id must be a non-empty string or null"
            )
        else:
            canonical_id = canonical_id_raw.strip()

        cardinality = item.get("cardinality", "UNRESOLVED")
        if cardinality not in ALLOWED_CARDINALITY:
            raise ValueError(f"invalid cardinality {cardinality!r} for {record_id}")
        if canonical_id is None and cardinality not in {"0:1", "UNRESOLVED"}:
            raise ValueError(f"cardinality {cardinality} requires canonical_id for {record_id}")
        if canonical_id is not None and cardinality == "0:1":
            raise ValueError(f"0:1 cardinality cannot include canonical_id for {record_id}")

        source_reference = item.get("source_reference")
        if source_reference is not None and (
            not isinstance(source_reference, str) or not source_reference.strip()
        ):
            raise ValueError(
                f"spatial_evidence[{index}].source_reference must be a non-empty string or null"
            )
        signature = (canonical_id, method, cardinality, source_reference)
        if signature in seen_candidates:
            raise ValueError(f"duplicate spatial evidence candidate for {record_id}: {signature!r}")
        seen_candidates.add(signature)

        state = "CANDIDATE_NOT_IDENTITY"
        reason = None
        if method in FORBIDDEN_METHODS:
            reason = f"forbidden sole identity method: {method}"
        elif not canonical_id:
            state = "UNRESOLVED"
            reason = "no canonical_id supplied"
        elif cardinality in {"1:N", "N:N", "UNRESOLVED"}:
            state = "UNRESOLVED"
            reason = "candidate set cardinality requires independent adjudication"
        elif method in {"STABLE_ID", "AUTHORITATIVE_BINDING"}:
            state = "PROVISIONAL"
        else:
            reason = "evidence retained as candidate; independent adjudication required"
        candidates.append(
            {
                "record_id": record_id,
                "record_id_raw": record_id_raw,
                "canonical_id": canonical_id,
                "canonical_id_raw": canonical_id_raw,
                "method": method,
                "cardinality": cardinality,
                "identity_state": state,
                "reason": reason,
                "source_reference": source_reference,
            }
        )
    if not candidates:
        candidates.append(
            {
                "record_id": record_id,
                "record_id_raw": record_id_raw,
                "canonical_id": None,
                "canonical_id_raw": None,
                "method": "NONE",
                "cardinality": "0:1",
                "identity_state": "UNRESOLVED",
                "reason": "no authoritative spatial evidence supplied",
                "source_reference": None,
            }
        )
    return {"record_id": record_id, "record_id_raw": record_id_raw, "bindings": candidates}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    rows = []
    for line_number, line in enumerate(
        args.input.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if line.strip():
            try:
                rows.append(adapt(json.loads(line)))
            except (json.JSONDecodeError, ValueError) as exc:
                p.error(f"input line {line_number}: {exc}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "\n".join(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in rows)
        + ("\n" if rows else ""),
        encoding="utf-8",
    )
    print(f"PASS records={len(rows)}; geometry_created=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
