"""Source-registry loader.

Reads `registries/source_registry.json` (stable wire format).
YAML is the human-editable source of truth; the JSON sibling is regenerated
via `scripts/regenerate_registry_json.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = "registries/source_registry.json"

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_source_registry(root: Path | None = None) -> dict[str, Any]:
    """Load the source registry as a dict. Caller may pass a custom root."""
    root = root or REPO_ROOT
    path = root / DEFAULT_REGISTRY_PATH
    return json.loads(path.read_text(encoding="utf-8"))


def required_sources(root: Path | None = None) -> list[dict[str, Any]]:
    """Return only the sources marked required=true."""
    reg = load_source_registry(root)
    return [s for s in reg.get("sources", []) if s.get("required")]


def all_sources(root: Path | None = None) -> list[dict[str, Any]]:
    """Return every declared source (required + optional)."""
    return load_source_registry(root).get("sources", [])


def source_by_id(source_id: str, root: Path | None = None) -> dict[str, Any] | None:
    """Look up a single source entry by source_id."""
    for s in all_sources(root):
        if s.get("source_id") == source_id:
            return s
    return None


def expected_outputs_for(source: dict[str, Any], root: Path | None = None) -> list[Path]:
    """Return resolved Path objects for each expected_output of a source."""
    root = root or REPO_ROOT
    return [root / p for p in source.get("expected_outputs", [])]


def producer_script_for(source: dict[str, Any], root: Path | None = None) -> Path | None:
    """Return resolved Path to the producer_script (or None if unset)."""
    root = root or REPO_ROOT
    script = source.get("producer_script")
    return (root / script) if script else None


def validate_registry(root: Path | None = None) -> dict[str, Any]:
    """Run lightweight integrity checks against the registry.

    Returns a dict with `errors` (blocking) and `warnings` (non-blocking).
    Errors raised:
      - duplicate source_id
      - missing producer_script file on disk
      - expected_outputs path traversal (`..` segments)
    Warnings:
      - required source without any expected_outputs declared
      - manual_export source without manual_drop_dir
    """
    root = root or REPO_ROOT
    reg = load_source_registry(root)
    sources = reg.get("sources", [])
    errors: list[str] = []
    warnings: list[str] = []
    seen: set[str] = set()
    for src in sources:
        sid = src.get("source_id")
        if not sid:
            errors.append(f"source missing source_id: {src!r}")
            continue
        if sid in seen:
            errors.append(f"duplicate source_id: {sid}")
        seen.add(sid)
        # producer_script
        script = src.get("producer_script")
        if script:
            if ".." in Path(script).parts:
                errors.append(f"{sid}: producer_script contains parent traversal")
            elif not (root / script).exists():
                errors.append(f"{sid}: producer_script not found: {script}")
        # expected_outputs
        outs = src.get("expected_outputs") or []
        for out in outs:
            if ".." in Path(out).parts:
                errors.append(f"{sid}: expected_output contains parent traversal: {out}")
        if src.get("required") and not outs:
            warnings.append(f"{sid}: required source has no expected_outputs declared")
        # manual_export check
        if src.get("authentication") == "manual_export" and not src.get("manual_drop_dir"):
            warnings.append(f"{sid}: manual_export source missing manual_drop_dir")
    return {
        "source_count": len(sources),
        "required_count": sum(1 for s in sources if s.get("required")),
        "errors": errors,
        "warnings": warnings,
        "ok": not errors,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--validate", action="store_true", help="Run validation checks")
    args = parser.parse_args(argv)
    if args.validate:
        report = validate_registry(args.root)
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1
    reg = load_source_registry(args.root)
    print(json.dumps({"source_count": len(reg.get("sources", []))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
