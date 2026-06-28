#!/usr/bin/env python3
"""Run the deterministic, audit-first maintenance layer for moneysweep-pr.

python3 scripts/run_maintenance.py --repo moneysweep-pr --mode audit
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from maintenance.runner import run_maintenance  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", default=None, help="program id (informational)")
    ap.add_argument("--mode", default="audit", choices=["audit", "safe-correct"])
    ap.add_argument("--no-write", action="store_true", help="do not write reports/maintenance/")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--fail-on-blocker", action="store_true", help="exit 1 if promotion is blocked")
    args = ap.parse_args()

    report = run_maintenance(root=REPO_ROOT, mode=args.mode, write=not args.no_write)
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{report.repo} maintenance ({args.mode}): "
            f"{payload['findings_count']} finding(s), "
            f"{payload['critical_count']} critical, "
            f"promotion_blocked={payload['promotion_blocked']}"
        )
        for finding in report.findings:
            print(f"  [{finding.severity:8}] {finding.category:16} {finding.message}")
    if args.fail_on_blocker and report.promotion_blocked:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
