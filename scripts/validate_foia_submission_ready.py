"""Pre-submission readiness validator for the FOIA request program.

Checks every condition that must be satisfied before the 9 FOIA requests can be
submitted:

  1. All 9 letter files exist in ``docs/foia_letters/``.
  2. ``data/reference/foia_requester.json`` contains no literal ``{{...}}``
     placeholder values (requester name and contact must be filled by the operator).
  3. Every request row has a non-empty ``priority`` and a valid ``request_status``.

Exits 0 if all checks pass; 1 if any fail.  Prints a per-request readiness
table and a summary.

CLI::

    python scripts/validate_foia_submission_ready.py
    python scripts/validate_foia_submission_ready.py --root /path/to/repo
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[1]

PRIORITY_QUEUE = "reports/foia_priority_queue.csv"
REQUESTER_CONFIG = "data/reference/foia_requester.json"
LETTERS_DIR = "docs/foia_letters"

VALID_STATUSES = {
    "planned", "drafted", "submitted", "awaiting_response",
    "partial_yield", "fulfilled", "denied", "appealed",
}


def validate(root: Path | None = None) -> list[str]:
    """Return a list of problems (empty == ready to submit)."""
    root = root or REPO_ROOT
    problems: list[str] = []

    # 1. Requester config must have real values.
    cfg_path = root / REQUESTER_CONFIG
    if not cfg_path.exists():
        problems.append(f"missing requester config: {REQUESTER_CONFIG}")
    else:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for key, val in cfg.items():
            if "{{" in str(val):
                problems.append(f"requester config field '{key}' still contains a placeholder: {val!r}")

    # 2. All letter files must exist.
    queue: list[dict[str, str]] = []
    with (root / PRIORITY_QUEUE).open(newline="", encoding="utf-8") as fh:
        queue = list(csv.DictReader(fh))

    letters_dir = root / LETTERS_DIR
    for row in queue:
        letter = letters_dir / f"{row['request_id']}.md"
        if not letter.exists():
            problems.append(f"missing letter file: {LETTERS_DIR}/{row['request_id']}.md")

    # 3. Per-row checks.
    for row in queue:
        if not (row.get("priority") or "").strip():
            problems.append(f"{row['request_id']}: missing priority")
        st = (row.get("request_status") or "").strip()
        if st not in VALID_STATUSES:
            problems.append(f"{row['request_id']}: invalid request_status {st!r}")

    return problems


def _print_table(root: Path) -> None:
    cfg_path = root / REQUESTER_CONFIG
    requester_filled = cfg_path.exists() and "{{" not in cfg_path.read_text(encoding="utf-8")
    letters_dir = root / LETTERS_DIR

    print(f"{'Request ID':<26} {'Priority':<8} {'Jurisdiction':<12} {'Status':<22} {'Letter':<8} {'Requester'}")
    print("-" * 95)
    with (root / PRIORITY_QUEUE).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            letter_ok = (letters_dir / f"{row['request_id']}.md").exists()
            print(
                f"{row['request_id']:<26} "
                f"{row.get('priority',''):<8} "
                f"{row.get('jurisdiction',''):<12} "
                f"{row.get('request_status',''):<22} "
                f"{'yes' if letter_ok else 'MISSING':<8} "
                f"{'filled' if requester_filled else 'PLACEHOLDER'}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate FOIA submission readiness.")
    parser.add_argument("--root", default=".")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()

    _print_table(root)
    print()

    problems = validate(root)
    if problems:
        print(f"NOT READY — {len(problems)} issue(s):")
        for p in problems:
            print(f"  ✗ {p}")
        return 1

    print("READY — all checks passed. Safe to submit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
