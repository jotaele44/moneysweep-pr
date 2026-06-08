"""Schema-registry loader.

Reads `registries/schema_registry.json`. Resolves canonical-column
references and validates that every column referenced by a table actually
exists in `canonical_columns`.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = "registries/schema_registry.json"

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_schema_registry(root: Path | None = None) -> dict[str, Any]:
    root = root or REPO_ROOT
    return json.loads((root / DEFAULT_REGISTRY_PATH).read_text(encoding="utf-8"))


def canonical_columns_for(table: str, root: Path | None = None) -> list[dict[str, Any]]:
    """Return resolved column dicts for a canonical table.

    Each entry has at least `name`. Columns declared with `ref` are resolved
    against `canonical_columns`, inheriting `dtype`/`required`/`description`.
    """
    reg = load_schema_registry(root)
    canon = reg.get("canonical_columns", {}) or {}
    tables = reg.get("canonical_tables", {}) or {}
    table_def = tables.get(table)
    if not table_def:
        raise KeyError(f"canonical table not found: {table}")
    resolved: list[dict[str, Any]] = []
    for col in table_def.get("columns", []):
        ref = col.get("ref")
        if ref:
            base = canon.get(ref, {})
            merged = {**base, **{k: v for k, v in col.items() if k != "ref"}}
            merged.setdefault("name", ref)
            resolved.append(merged)
        else:
            resolved.append(col)
    return resolved


def primary_key_for(table: str, root: Path | None = None) -> list[str]:
    reg = load_schema_registry(root)
    return list(reg.get("canonical_tables", {}).get(table, {}).get("primary_key", []))


def all_tables(root: Path | None = None) -> list[str]:
    return list(load_schema_registry(root).get("canonical_tables", {}).keys())


def validate_registry(root: Path | None = None) -> dict[str, Any]:
    """Validate that every column ref resolves and every PK column is present."""
    reg = load_schema_registry(root)
    canon = reg.get("canonical_columns", {}) or {}
    tables = reg.get("canonical_tables", {}) or {}
    errors: list[str] = []
    warnings: list[str] = []
    for tname, tdef in tables.items():
        cols = tdef.get("columns", []) or []
        names: list[str] = []
        for col in cols:
            ref = col.get("ref")
            cname = col.get("name") or ref
            if not cname:
                errors.append(f"{tname}: column entry missing both name and ref: {col!r}")
                continue
            if ref and ref not in canon:
                errors.append(f"{tname}.{cname}: unknown canonical ref '{ref}'")
            names.append(cname)
        for pk in tdef.get("primary_key", []) or []:
            if pk not in names:
                errors.append(f"{tname}: primary_key '{pk}' not in declared columns")
        if not cols:
            warnings.append(f"{tname}: table has no columns declared")
    return {
        "table_count": len(tables),
        "canonical_column_count": len(canon),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args(argv)
    if args.validate:
        report = validate_registry(args.root)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    print(json.dumps({"tables": all_tables(args.root)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
