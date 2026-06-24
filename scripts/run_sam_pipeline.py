"""
SAM pipeline — one command, monthly.

Runs, in order:
  1. ingest_sam_bulk.py     offline bulk join against newest SAM_PUBLIC_MONTHLY_V2_*.dat
                            (resolves the bulk of vendors + confirms k2 candidates, no API)
  2. sam_enrichment.py      API mop-up of the residual, with a daily-quota guard
                            (skip with --skip-api; cap with --max-api, default 900)
  3. merge_sam_bulk_master  fold authoritative + confirmed matches into master_enriched.csv

Each step is independently resumable. The API step is rate-limited (SAM allows
~1,000 requests/day); --max-api stops cleanly and checkpoints, so rerunning the
next day continues where it left off.

Usage:
  python3 scripts/run_sam_pipeline.py                 # full monthly run
  python3 scripts/run_sam_pipeline.py --skip-api      # offline only (bulk + merge)
  python3 scripts/run_sam_pipeline.py --max-api 500   # tighter daily budget
  python3 scripts/run_sam_pipeline.py --dat /path/to/extract.dat
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable or "python3"


def step(title: str, cmd: list[str], allow_failure: bool = False) -> None:
    print(f"\n{'=' * 64}\n[STEP] {title}\n{'=' * 64}", flush=True)
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        if allow_failure:
            # sam_enrichment exits non-zero when the coverage gate fails; that is
            # a warning for the residual mop-up, not a pipeline-fatal error.
            print(f"[WARN] step '{title}' returned {r.returncode} (continuing)", flush=True)
            return
        raise SystemExit(f"[FAIL] step '{title}' returned {r.returncode}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Run the full SAM resolution pipeline")
    ap.add_argument("--dat", help="Path to SAM_PUBLIC_MONTHLY_V2_*.dat (default: auto-detect)")
    ap.add_argument("--skip-api", action="store_true", help="Offline only: bulk join + merge")
    ap.add_argument(
        "--max-api", type=int, default=900, help="Daily API lookup budget (default 900)"
    )
    args = ap.parse_args()

    bulk = [PY, "scripts/ingest_sam_bulk.py"]
    if args.dat:
        bulk += ["--dat", args.dat]
    step("1/3 Offline bulk join + k2 confirmation", bulk)

    if args.skip_api:
        print("\n[SKIP] API residual step (--skip-api)", flush=True)
    else:
        step(
            "2/3 API residual mop-up (quota-guarded)",
            [PY, "scripts/sam_enrichment.py", "--resume", "--max-api", str(args.max_api)],
            allow_failure=True,
        )

    step("3/3 Merge into master_enriched.csv", [PY, "scripts/merge_sam_bulk_master.py"])

    print(
        f"\n{'=' * 64}\n[DONE] SAM pipeline complete.\n"
        f"  master:  data/staging/processed/enrichment/master_enriched.csv\n"
        f"  review:  data/staging/processed/enrichment/sam_bulk_v2_review.csv\n"
        f"{'=' * 64}",
        flush=True,
    )


if __name__ == "__main__":
    main()
