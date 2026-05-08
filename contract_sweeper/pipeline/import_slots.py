"""Manual import slot builders for R4.7 backfill runner scaffolding."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _family_slug(source_family: str) -> str:
    slug = "".join(ch if ch.isalnum() else "_" for ch in source_family.lower())
    while "__" in slug:
        slug = slug.replace("__", "_")
    return slug.strip("_") or "source"


def dropzone_path_for(source_family: str, expected_input: str) -> str:
    filename = Path(expected_input).name
    return f"data/manual_import_dropzone/{_family_slug(source_family)}/{filename}"


def accepted_patterns_for(source_family: str) -> str:
    family = source_family.lower()
    if "usaspending" in family or "federal_awards" in family:
        return "*.csv|*.xlsx|*.xls"
    if "fema" in family or "hud" in family:
        return "*.csv|*.xlsx"
    if "fsrs" in family:
        return "*.csv"
    return "*.csv|*.xlsx|*.xls|*.parquet"


def validation_command_for(target_output_path: str, required_columns: list[str]) -> str:
    req = ",".join(required_columns)
    return (
        "python -c \"import pandas as pd; from pathlib import Path; "
        f"p=Path('{target_output_path}'); assert p.exists(), 'missing output'; "
        "df=pd.read_csv(p,dtype=str,low_memory=False); "
        "assert len(df)>0, 'empty output'; "
        f"req='{req}'.split(',') if '{req}' else []; "
        "missing=[c for c in req if c and c not in df.columns]; "
        "assert not missing, f'missing columns: {missing}'; "
        "print('rows',len(df))\""
    )


def build_manual_slot(
    row: dict[str, Any],
    *,
    source_family: str,
    required_columns: list[str],
    manifest_output_path: str,
) -> dict[str, Any]:
    expected_input = str(row.get("expected_input", ""))
    slot_id = f"slot_{int(row.get('priority', 0)):02d}_{Path(expected_input).stem}"
    target_output_path = str(row.get("target_output_path") or expected_input)

    return {
        "slot_id": slot_id,
        "source_family": source_family,
        "expected_input": expected_input,
        "dropzone_path": dropzone_path_for(source_family, expected_input),
        "accepted_file_patterns": accepted_patterns_for(source_family),
        "required_columns": "|".join(required_columns),
        "target_output_path": target_output_path,
        "validation_command": validation_command_for(target_output_path, required_columns),
        "manifest_output_path": manifest_output_path,
    }
