#!/usr/bin/env python3
"""Offline, receipt-bound Cell_Profile materialization for a domain repository."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pr_grid_v2_profiles import ProfileError, build_profiles, digest
from pr_grid_v2_runtime import GridV2PinError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pin",
        type=Path,
        default=Path(__file__).with_name("pr_grid_geographic_v2.pin.json"),
    )
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--bindings", type=Path, required=True)
    parser.add_argument("--binding-receipt", type=Path, required=True)
    parser.add_argument("--coverage", type=Path)
    parser.add_argument("--level", choices=("L0", "L1", "L2", "L3"), required=True)
    parser.add_argument("--cell-id", action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--receipt-out", type=Path, required=True)
    args = parser.parse_args()
    try:
        profiles, receipt = build_profiles(
            pin_path=args.pin,
            records_path=args.records,
            bindings_path=args.bindings,
            receipt_path=args.binding_receipt,
            coverage_path=args.coverage,
            level=args.level,
            requested_cells=tuple(args.cell_id),
        )
    except (ProfileError, GridV2PinError, OSError, ValueError) as exc:
        parser.exit(2, f"FAIL_CLOSED: {exc}\n")
    output = "".join(
        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in profiles
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(output, encoding="utf-8")
    receipt["Output_SHA256"] = digest(output.encode("utf-8"))
    args.receipt_out.parent.mkdir(parents=True, exist_ok=True)
    args.receipt_out.write_text(
        json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
