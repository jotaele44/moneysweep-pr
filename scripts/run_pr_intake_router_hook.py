#!/usr/bin/env python3
"""Safe orchestrator hook for the PR intake router.

This module is intentionally small so it can be called from a future `run_all.py`
refactor without embedding router logic in the main pipeline orchestrator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from scripts import route_pr_intake


DEFAULT_INPUT = Path("data/intake/pr_news/raw_items_latest.jsonl")
DEFAULT_OUT_DIR = Path("data/exports/pr_intake_router")


def run(
    input_path: str | Path = DEFAULT_INPUT,
    out_dir: str | Path = DEFAULT_OUT_DIR,
    *,
    fail_on_validation_errors: bool = False,
) -> int:
    """Run the PR intake router if the input file exists.

    Returns:
        0 when routing succeeds or no input is available.
        Non-zero return code from route_pr_intake on validation/export failure.
    """

    input_path = Path(input_path)
    out_dir = Path(out_dir)

    if not input_path.exists():
        print(f"[pr-intake-router] SKIPPED — input not found: {input_path}")
        return 0

    argv = [
        "--input",
        str(input_path),
        "--out-dir",
        str(out_dir),
    ]
    if fail_on_validation_errors:
        argv.append("--fail-on-validation-errors")

    return route_pr_intake.main_with_args(argv)


if __name__ == "__main__":
    raise SystemExit(run())
