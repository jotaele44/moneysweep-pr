#!/usr/bin/env python3
"""Root-level runner for PR intake router exports.

Equivalent to:
    python scripts/route_pr_intake.py --input <raw_items> --out-dir <exports>

This intentionally keeps the PR intake router callable without modifying the
large moneysweep-pr run_all.py orchestrator until a safer full orchestrator
refactor is made.
"""

from __future__ import annotations

from scripts.route_pr_intake import main


if __name__ == "__main__":
    raise SystemExit(main())
