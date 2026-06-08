#!/usr/bin/env python3
"""Run PR News raw-intake production and PR intake routing as one safe handoff.

This is the controlled integration boundary for future `run_all.py` wiring:

    PR News incoming items
    → data/intake/pr_news/raw_items_latest.jsonl
    → PR intake router exports
    → export verification
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Mapping, Sequence

from scripts import produce_pr_news_raw_intake
from scripts.run_pr_intake_router_hook import run as run_router_hook


DEFAULT_INCOMING = Path("data/intake/pr_news/incoming_items_latest.jsonl")
DEFAULT_RAW = Path("data/intake/pr_news/raw_items_latest.jsonl")
DEFAULT_MANIFEST = Path("data/intake/pr_news/raw_items_latest_manifest.json")
DEFAULT_EXPORT_DIR = Path("data/exports/pr_intake_router")

EXPECTED_EXPORTS = (
    "route_results.jsonl",
    "contract_sweeper_derivatives.csv",
    "spiderweb_pr_derivatives.csv",
    "manual_review_queue.csv",
    "routing_summary.json",
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Produce PR News raw intake and route it into repo derivatives."
    )
    parser.add_argument(
        "--incoming", default=str(DEFAULT_INCOMING), help="Incoming PR News JSONL/JSON/CSV path."
    )
    parser.add_argument(
        "--raw-output", default=str(DEFAULT_RAW), help="Router-ready raw JSONL output path."
    )
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST), help="Producer manifest path.")
    parser.add_argument(
        "--export-dir", default=str(DEFAULT_EXPORT_DIR), help="Router export directory."
    )
    parser.add_argument(
        "--strict-missing-input",
        action="store_true",
        help="Fail if incoming PR News input is missing.",
    )
    parser.add_argument(
        "--fail-on-validation-errors",
        action="store_true",
        help="Router exits non-zero if validation errors exist.",
    )
    return parser.parse_args(argv)


def verify_exports(export_dir: str | Path = DEFAULT_EXPORT_DIR) -> Mapping[str, object]:
    export_dir = Path(export_dir)
    files = {name: (export_dir / name).exists() for name in EXPECTED_EXPORTS}
    return {
        "export_dir": str(export_dir),
        "files": files,
        "all_exports_exist": all(files.values()),
    }


def main_with_args(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    producer_rc = produce_pr_news_raw_intake.main_with_args(
        [
            "--input",
            str(args.incoming),
            "--output",
            str(args.raw_output),
            "--manifest",
            str(args.manifest),
            *(["--strict-missing-input"] if args.strict_missing_input else []),
        ]
    )
    if producer_rc not in (0,):
        return producer_rc

    router_rc = run_router_hook(
        input_path=args.raw_output,
        out_dir=args.export_dir,
        fail_on_validation_errors=args.fail_on_validation_errors,
    )
    if router_rc != 0:
        return router_rc

    verification = verify_exports(args.export_dir)
    (Path(args.export_dir) / "export_verification.json").write_text(
        json.dumps(dict(verification), indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(dict(verification), indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if verification["all_exports_exist"] else 1


def main() -> int:
    return main_with_args()


if __name__ == "__main__":
    raise SystemExit(main())
