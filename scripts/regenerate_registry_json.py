"""Regenerate JSON siblings of the YAML registries and override fragments."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    # Raise rather than sys.exit(): this module is imported by tests and by
    # pre-commit, and a module-level exit takes the whole interpreter down
    # (pytest reports INTERNALERROR and collects nothing) instead of failing
    # this one import.
    raise ImportError(
        "PyYAML is required to regenerate registry JSONs. Install with: pip install PyYAML"
    ) from exc

REGISTRY_PAIRS = [
    ("source_registry.yaml", "source_registry.json"),
    ("schema_registry.yaml", "schema_registry.json"),
    ("manual_export_registry.yaml", "manual_export_registry.json"),
    ("endpoint_candidates.yaml", "endpoint_candidates.json"),
    ("coverage_contracts.yaml", "coverage_contracts.json"),
    ("government_entity_registry.yaml", "government_entity_registry.json"),
]


def _write_pair(source: Path, destination: Path) -> None:
    data = yaml.safe_load(source.read_text(encoding="utf-8"))
    destination.write_text(json.dumps(data, indent=2, sort_keys=False), encoding="utf-8")


def regenerate(registries_dir: Path) -> int:
    written = 0
    for yaml_name, json_name in REGISTRY_PAIRS:
        source = registries_dir / yaml_name
        destination = registries_dir / json_name
        if not source.exists():
            print(f"skip: {source} does not exist")
            continue
        _write_pair(source, destination)
        print(f"wrote {destination.relative_to(registries_dir.parent)}")
        written += 1

    overrides_dir = registries_dir / "source_registry_overrides"
    if overrides_dir.exists():
        for source in sorted(overrides_dir.glob("*.yaml")):
            destination = source.with_suffix(".json")
            _write_pair(source, destination)
            print(f"wrote {destination.relative_to(registries_dir.parent)}")
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
