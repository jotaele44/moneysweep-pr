"""Regenerate JSON siblings of the YAML registries.

YAML is the human-editable source of truth in `registries/*.yaml`.
JSON is the runtime wire format read by `contract_sweeper.runtime.*`.
Run this after editing any YAML registry.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print(
        "PyYAML is required to regenerate registry JSONs. "
        "Install with: pip install PyYAML",
        file=sys.stderr,
    )
    sys.exit(2)


REGISTRY_PAIRS = [
    ("source_registry.yaml", "source_registry.json"),
    ("schema_registry.yaml", "schema_registry.json"),
    ("manual_export_registry.yaml", "manual_export_registry.json"),
    ("endpoint_candidates.yaml", "endpoint_candidates.json"),
]


def regenerate(registries_dir: Path) -> int:
    written = 0
    for yaml_name, json_name in REGISTRY_PAIRS:
        src = registries_dir / yaml_name
        dst = registries_dir / json_name
        if not src.exists():
            print(f"skip: {src} does not exist")
            continue
        data = yaml.safe_load(src.read_text(encoding="utf-8"))
        dst.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")
        print(f"wrote {dst.relative_to(registries_dir.parent)}")
        written += 1
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registries-dir",
        default=Path(__file__).resolve().parent.parent / "registries",
        type=Path,
    )
    args = parser.parse_args(argv)
    regenerate(args.registries_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
