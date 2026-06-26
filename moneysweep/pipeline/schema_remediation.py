"""Schema remediation helpers for R4.8C backfill failure analysis."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

CANONICAL_ALIAS_HINTS: dict[str, list[str]] = {
    "recipient_name_normalized": [
        "recipient_name",
        "sub_awardee_name",
        "prime_recipient_name",
        "vendor_name",
    ],
    "recipient_uei": [
        "uei",
        "recipient_unique_entity_id",
        "sam_uei",
        "duns",
    ],
    "awarding_sub_agency": [
        "awarding_agency",
        "awarding_subagency",
        "sub_agency",
        "funding_sub_agency",
    ],
    "source_system": [
        "source_dataset",
        "source_file",
        "source",
        "dataset",
    ],
    "source_record_id": [
        "award_id",
        "prime_award_id",
        "generated_internal_id",
        "sub_award_id",
    ],
    "source_lineage_path": [
        "source_file",
        "download_path",
        "lineage_path",
    ],
    "source_lineage_mode": [
        "source_dataset",
        "source_mode",
        "ingest_mode",
    ],
    "pop_county": [
        "place_of_performance_county",
        "place_of_performance_city",
        "county",
    ],
    "award_date": [
        "start_date",
        "action_date",
        "sub_award_date",
    ],
    "obligated_amount": [
        "award_amount",
        "sub_award_amount",
        "total_obligation",
    ],
}


def split_pipe(raw: Any) -> list[str]:
    return [part.strip() for part in str(raw or "").split("|") if part.strip()]


def _normalize_token(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text).lower())


def read_observed_columns(root: Path, target_output_path: str) -> list[str]:
    root = Path(root)
    path = root / str(target_output_path or "")
    if not path.exists() or not path.is_file():
        return []

    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            frame = pd.read_csv(path, dtype=str, low_memory=False, nrows=0)
            return [str(col) for col in frame.columns]
        if suffix == ".parquet":
            frame = pd.read_parquet(path)
            return [str(col) for col in frame.columns]
    except Exception:
        return []

    return []


def infer_candidate_column_aliases(
    required_columns: list[str],
    observed_columns: list[str],
) -> dict[str, list[str]]:
    observed = [col for col in observed_columns if str(col).strip()]
    observed_norm = {_normalize_token(col): col for col in observed}

    candidates: dict[str, list[str]] = {}
    for required in required_columns:
        req = str(required).strip()
        if not req:
            continue

        req_norm = _normalize_token(req)
        if req_norm in observed_norm:
            continue

        ranked: list[str] = []

        for hint in CANONICAL_ALIAS_HINTS.get(req, []):
            hint_norm = _normalize_token(hint)
            if hint_norm in observed_norm:
                ranked.append(observed_norm[hint_norm])

        if not ranked:
            for obs in observed:
                obs_norm = _normalize_token(obs)
                if not obs_norm:
                    continue
                if req_norm in obs_norm or obs_norm in req_norm:
                    ranked.append(obs)

        deduped: list[str] = []
        for item in ranked:
            if item not in deduped:
                deduped.append(item)

        candidates[req] = deduped

    return candidates


def build_recommended_mapping(candidate_aliases: dict[str, list[str]]) -> dict[str, str]:
    recommended: dict[str, str] = {}
    for required, candidates in candidate_aliases.items():
        if candidates:
            recommended[required] = candidates[0]
    return recommended


def serialize_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True)
