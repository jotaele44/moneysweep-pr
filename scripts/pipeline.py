"""Canonical pipeline entry point for Contract-Sweeper.

Chains the full PR federal-contracting data pipeline in the correct order.
Each step is an independently-runnable script; this file wires them together.

Usage:
  python scripts/pipeline.py all          # full pipeline: validate→build→signals→report
  python scripts/pipeline.py validate     # run validation gates only
  python scripts/pipeline.py build        # build unified master + execution chains
  python scripts/pipeline.py signals      # compute R7 risk signals
  python scripts/pipeline.py report       # generate investigative report
  python scripts/pipeline.py status       # print gate status, always exits 0
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_PYTHON = sys.executable

# Ordered steps for the full pipeline
_STEPS: dict[str, list[str]] = {
    "validate": [
        [_PYTHON, "-m", "contract_sweeper.runtime.validation_gates", "--root", str(ROOT)],
    ],
    "build": [
        [_PYTHON, str(ROOT / "scripts" / "build_unified_master.py")],
        [_PYTHON, str(ROOT / "scripts" / "execution_chain_builder.py")],
        [_PYTHON, str(ROOT / "scripts" / "parent_collapse.py")],
    ],
    "signals": [
        [_PYTHON, str(ROOT / "scripts" / "build_risk_signals.py"), "--root", str(ROOT)],
    ],
    "report": [
        [_PYTHON, str(ROOT / "scripts" / "generate_report.py")],
    ],
}

_ALL_ORDER = ["validate", "build", "signals", "report"]


def _run(cmd: list[str]) -> int:
    print(f"\n[pipeline] {' '.join(str(c) for c in cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=str(ROOT))
    return result.returncode


def run_step(step: str, fail_fast: bool = True) -> int:
    cmds = _STEPS[step]
    for cmd in cmds:
        rc = _run(cmd)
        if rc != 0:
            print(f"\n[pipeline] FAILED at step '{step}' (exit {rc})", file=sys.stderr)
            if fail_fast:
                return rc
    return 0


def run_all() -> int:
    for step in _ALL_ORDER:
        rc = run_step(step)
        if rc != 0:
            return rc
    print("\n[pipeline] All steps completed successfully.")
    return 0


def run_status() -> int:
    """Print current gate status without failing on gate errors."""
    cmd = [_PYTHON, "-m", "contract_sweeper.runtime.validation_gates",
           "--root", str(ROOT), "--allow-failed"]
    subprocess.run(cmd, cwd=str(ROOT))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Contract-Sweeper canonical pipeline runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "step",
        choices=list(_STEPS.keys()) + ["all", "status"],
        help="Pipeline step to run",
    )
    args = parser.parse_args()

    if args.step == "all":
        sys.exit(run_all())
    elif args.step == "status":
        sys.exit(run_status())
    else:
        sys.exit(run_step(args.step))


if __name__ == "__main__":
    main()
