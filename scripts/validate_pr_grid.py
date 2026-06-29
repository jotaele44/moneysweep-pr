#!/usr/bin/env python3
"""Validate the Puerto Rico federation baseline grid CSV."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

EXPECTED_COLUMNS = ['Cell_ID', 'Row_Index', 'Column_Index', 'Pixel_X_Min', 'Pixel_Y_Min', 'Pixel_X_Max', 'Pixel_Y_Max', 'Centroid_X', 'Centroid_Y', 'Dark_Pixel_Count', 'Total_Pixel_Count', 'Land_Pixel_Ratio', 'Classification']
EXPECTED_ROWS = 98_304
EXPECTED_ROW_MAX = 255
EXPECTED_COLUMN_MAX = 383
EXPECTED_CLASSIFICATIONS = {'Gridline_Dominant', 'Water_or_Empty', 'Coastline_or_Land'}
EXPECTED_SHA256 = "17733f3f18c8a644e31c1eb25fb27b73b4bf353c6de57d5203c4311e05d64483"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_grid(path: Path, *, require_sha: bool = False) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing grid CSV: {path}"]
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_COLUMNS:
            errors.append(f"unexpected columns: {reader.fieldnames}")
        row_count = 0
        seen_ids: set[str] = set()
        row_values: set[int] = set()
        column_values: set[int] = set()
        for line_number, row in enumerate(reader, start=2):
            row_count += 1
            cell_id = row.get("Cell_ID", "")
            if cell_id in seen_ids:
                errors.append(f"duplicate Cell_ID at line {line_number}: {cell_id}")
            seen_ids.add(cell_id)
            try:
                row_index = int(row["Row_Index"])
                column_index = int(row["Column_Index"])
                total_pixels = int(row["Total_Pixel_Count"])
                dark_pixels = int(row["Dark_Pixel_Count"])
                land_ratio = float(row["Land_Pixel_Ratio"])
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"invalid numeric field at line {line_number}: {exc}")
                continue
            row_values.add(row_index)
            column_values.add(column_index)
            if not (0 <= row_index <= EXPECTED_ROW_MAX):
                errors.append(f"Row_Index out of bounds at line {line_number}: {row_index}")
            if not (0 <= column_index <= EXPECTED_COLUMN_MAX):
                errors.append(f"Column_Index out of bounds at line {line_number}: {column_index}")
            if dark_pixels < 0 or total_pixels <= 0 or dark_pixels > total_pixels:
                errors.append(f"invalid pixel counts at line {line_number}")
            if not (0.0 <= land_ratio <= 1.0):
                errors.append(f"Land_Pixel_Ratio out of range at line {line_number}: {land_ratio}")
            classification = row.get("Classification", "")
            if classification not in EXPECTED_CLASSIFICATIONS:
                errors.append(f"unexpected Classification at line {line_number}: {classification}")
    if row_count != EXPECTED_ROWS:
        errors.append(f"unexpected row count: {row_count} != {EXPECTED_ROWS}")
    if len(seen_ids) != EXPECTED_ROWS:
        errors.append(f"unexpected unique Cell_ID count: {len(seen_ids)} != {EXPECTED_ROWS}")
    if row_values != set(range(EXPECTED_ROW_MAX + 1)):
        errors.append("Row_Index coverage is not complete 0..255")
    if column_values != set(range(EXPECTED_COLUMN_MAX + 1)):
        errors.append("Column_Index coverage is not complete 0..383")
    if require_sha:
        actual_sha = _sha256(path)
        if actual_sha != EXPECTED_SHA256:
            errors.append(f"unexpected SHA-256: {actual_sha} != {EXPECTED_SHA256}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", default="registry/spatial/pr_grid_full_cell_index_saturated.csv")
    parser.add_argument("--require-sha", action="store_true")
    args = parser.parse_args()
    errors = validate_grid(Path(args.grid), require_sha=args.require_sha)
    if errors:
        print("[FAIL] PR baseline grid validation failed", file=sys.stderr)
        for error in errors:
            print(f" - {error}", file=sys.stderr)
        return 1
    print("[OK] PR baseline grid validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
