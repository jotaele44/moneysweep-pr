#!/usr/bin/env python3
"""Materialize the frozen MII v0.3 reference as noncanonical source rows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from moneysweep.entity_network.mii_v03 import (
    REFERENCE_DIR,
    materialize_provisional_snapshot,
    validate_reference_bundle,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/staging/entity_network/mii_v0_3"),
    )
    parser.add_argument(
        "--check-reference",
        action="store_true",
        help="validate committed aggregate ledgers without source bytes",
    )
    args = parser.parse_args()

    results = {}
    if args.check_reference:
        results["reference"] = validate_reference_bundle(REFERENCE_DIR)

    supplied = (args.pdf is not None, args.zip_path is not None)
    if any(supplied) and not all(supplied):
        parser.error("--pdf and --zip must be supplied together")
    if all(supplied):
        results["materialization"] = materialize_provisional_snapshot(
            args.pdf,
            args.zip_path,
            args.output_dir,
        )
    if not results:
        parser.error("choose --check-reference and/or supply --pdf plus --zip")

    print(json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
