"""Merge LegislaPR registry entries into the main source registry.

Updates `registries/source_registry.yaml` and `registries/source_registry.json`
from the LegislaPR extension file. Use `--check` to fail when the main registry
has not yet absorbed the entries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    print("PyYAML is required. Install with: pip install PyYAML", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_YAML = ROOT / "registries" / "source_registry.yaml"
REGISTRY_JSON = ROOT / "registries" / "source_registry.json"
EXTENSION_JSON = ROOT / "registries" / "source_registry_extensions" / "legislapr_discovery.json"


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_sources(registry: dict[str, Any], incoming: list[dict[str, Any]]) -> tuple[dict[str, Any], bool]:
    existing = registry.setdefault("sources", [])
    by_id = {src.get("source_id"): index for index, src in enumerate(existing)}
    changed = False
    for src in incoming:
        sid = src.get("source_id")
        if not sid:
            continue
        if sid in by_id:
            if existing[by_id[sid]] != src:
                existing[by_id[sid]] = src
                changed = True
        else:
            existing.append(src)
            changed = True
    return registry, changed


def merge(check: bool = False) -> dict[str, Any]:
    registry = _load_yaml(REGISTRY_YAML)
    incoming = _load_json(EXTENSION_JSON).get("sources", [])
    merged, changed = _merge_sources(registry, incoming)
    source_ids = [src.get("source_id") for src in merged.get("sources", [])]
    duplicate_ids = sorted({sid for sid in source_ids if source_ids.count(sid) > 1})
    if duplicate_ids:
        raise RuntimeError(f"duplicate source IDs after merge: {duplicate_ids}")
    if check and changed:
        raise RuntimeError("main source registry is missing LegislaPR sources")
    if not check and changed:
        REGISTRY_YAML.write_text(yaml.safe_dump(merged, sort_keys=False, allow_unicode=True), encoding="utf-8")
        REGISTRY_JSON.write_text(json.dumps(merged, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "changed": changed,
        "incoming_sources": [src.get("source_id") for src in incoming],
        "source_count": len(merged.get("sources", [])),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    print(json.dumps(merge(check=args.check), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
