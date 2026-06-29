#!/usr/bin/env python3
"""Validate the committed federal-publications federation sources.

`data/sources/federal_publications.jsonl` is produced by
`scripts/ingest_federal_publications.py` from an external "PR Federal
Publications Master" workbook and folded into the canonical_v1 evidence layer by
`scripts/bridge_canonical_v1_federation.py:merge_external_sources()`. The source
workbook lives outside the repo, so CI cannot regenerate the file — instead this
metadata-only validator guards the committed artifact against drift.

It is stdlib-only (no jsonschema dependency, matching the other `validate_*.py`
scripts) and schema-driven: the required fields and the `source_id` pattern are
read from `schemas/moneysweep_source.schema.json`, so this stays in sync if the
schema changes. Checks:

  * every row carries the schema's required keys;
  * `source_id` matches the schema's `^src_[a-f0-9]{32}$` pattern;
  * `lineage` is an object with its required sub-keys;
  * each row satisfies the schema's anyOf (a `source_url` or a `source_ref`);
  * `synthetic` is a bool and `confidence` is a number in [0, 1];
  * `source_id`s are unique;
  * the row count is at least the expected baseline.

Exit code 0 when clean, 1 on any violation. No network, no API keys.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_DATA = REPO_ROOT / "data" / "sources" / "federal_publications.jsonl"
DEFAULT_SCHEMA = REPO_ROOT / "schemas" / "moneysweep_source.schema.json"

# The fold has carried 4248 sources since it landed; the count must not regress.
MIN_ROWS = 4248
# How many individual row errors to print before truncating the report.
MAX_REPORTED = 25


def _load_schema(path: Path) -> dict[str, Any]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return schema


def _iter_rows(path: Path):
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            yield lineno, json.loads(line)


def _anyof_keys(schema: dict[str, Any]) -> list[list[str]]:
    """Required-key groups from the schema's top-level anyOf (e.g. url OR ref)."""
    groups = []
    for clause in schema.get("anyOf", []):
        req = clause.get("required")
        if req:
            groups.append(list(req))
    return groups


def validate(data_path: Path, schema_path: Path) -> list[str]:
    """Return a list of human-readable errors (empty means valid)."""
    errors: list[str] = []
    schema = _load_schema(schema_path)

    required = schema.get("required", [])
    id_pattern = re.compile(schema["properties"]["source_id"]["pattern"])
    lineage_required = schema["definitions"]["lineage"]["required"]
    anyof_groups = _anyof_keys(schema)

    seen_ids: dict[str, int] = {}
    count = 0

    for lineno, row in _iter_rows(data_path):
        count += 1
        prefix = f"line {lineno}"

        missing = [k for k in required if k not in row]
        if missing:
            errors.append(f"{prefix}: missing required keys {missing}")

        sid = row.get("source_id")
        if isinstance(sid, str):
            if not id_pattern.match(sid):
                errors.append(f"{prefix}: source_id {sid!r} does not match {id_pattern.pattern}")
            if sid in seen_ids:
                errors.append(
                    f"{prefix}: duplicate source_id {sid!r} (first seen line {seen_ids[sid]})"
                )
            else:
                seen_ids[sid] = lineno

        lineage = row.get("lineage")
        if not isinstance(lineage, dict):
            errors.append(f"{prefix}: lineage must be an object")
        else:
            lmissing = [k for k in lineage_required if k not in lineage]
            if lmissing:
                errors.append(f"{prefix}: lineage missing {lmissing}")

        if anyof_groups and not any(all(k in row for k in grp) for grp in anyof_groups):
            errors.append(f"{prefix}: row satisfies none of anyOf {anyof_groups}")

        if "synthetic" in row and not isinstance(row["synthetic"], bool):
            errors.append(f"{prefix}: synthetic must be a boolean")

        conf = row.get("confidence")
        if conf is not None and (not isinstance(conf, (int, float)) or not 0.0 <= conf <= 1.0):
            errors.append(f"{prefix}: confidence {conf!r} must be a number in [0, 1]")

    if count < MIN_ROWS:
        errors.append(f"row count {count} is below the expected baseline of {MIN_ROWS}")

    return errors


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--data", type=Path, default=DEFAULT_DATA, help="federal_publications.jsonl path"
    )
    ap.add_argument(
        "--schema", type=Path, default=DEFAULT_SCHEMA, help="moneysweep_source schema path"
    )
    args = ap.parse_args()

    if not args.data.is_file():
        print(f"ERROR: data file not found: {args.data}", file=sys.stderr)
        return 1
    if not args.schema.is_file():
        print(f"ERROR: schema file not found: {args.schema}", file=sys.stderr)
        return 1

    errors = validate(args.data, args.schema)
    total = sum(1 for _ in _iter_rows(args.data))

    if errors:
        print(
            f"FAIL: {len(errors)} problem(s) in {args.data.name} ({total} rows):", file=sys.stderr
        )
        for e in errors[:MAX_REPORTED]:
            print(f"  - {e}", file=sys.stderr)
        if len(errors) > MAX_REPORTED:
            print(f"  ... and {len(errors) - MAX_REPORTED} more", file=sys.stderr)
        return 1

    print(f"OK: {total} federal-publication sources valid against {args.schema.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
