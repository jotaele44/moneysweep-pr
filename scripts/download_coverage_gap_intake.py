"""Coverage-gap intake — deferred producer (intentionally not implemented).

Registered ``producer_script`` for P1 financial sources promoted from the
coverage-gap backlog (``reports/financial_source_coverage_gaps.md``) into the
registry as tracked intake stubs:

  - ``hacienda_sut_ivu``      PR Treasury Sales & Use Tax (IVU/SUT) collections (scraper surface)
  - ``census_gov_finances``   Census Annual Survey of State & Local Government Finances (PR)
  - ``fta_ntd``               FTA National Transit Database — PR transit agency finance

Like ``scripts/download_nara_nextgen.py``, declaring this producer keeps the
readiness preflight honest: each source resolves to a real, importable, callable
producer instead of a fatal ``missing_producer`` structural error, while ``run``
performs no network I/O and materializes nothing — so the sources correctly remain
``not_materialized`` until a real fetcher/adapter is built (network egress or an
API key is required, which the buildout environment does not have).

Usage:
  python3 scripts/download_coverage_gap_intake.py [--source <source_id>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging

# Source IDs this producer serves (mirrors the registry entries).
COVERAGE_GAP_SOURCE_IDS = ("hacienda_sut_ivu", "census_gov_finances", "fta_ntd")


def run(root: Path | None = None, source_id: str | None = None, **_kwargs) -> dict:
    """Deferred no-op entrypoint.

    Performs no network calls and writes no outputs. Returns a result dict in the
    shape other producers use so an accidental pipeline invocation degrades
    gracefully rather than raising.
    """
    logger = setup_logging("coverage_gap_intake")
    targets = [source_id] if source_id else list(COVERAGE_GAP_SOURCE_IDS)
    for sid in targets:
        logger.info(
            f"[coverage_gap_intake] {sid}: fetcher/adapter not yet built — needs network "
            f"egress or API key. Skipping (0 rows, not_materialized)."
        )
    return {
        "rows": 0,
        "status": "deferred",
        "materialized": False,
        "sources": targets,
        "reason": "intake stub; real fetcher intentionally not implemented yet",
    }


# Entrypoint aliases recognized by the pipeline readiness preflight.
main = run
download = run


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=COVERAGE_GAP_SOURCE_IDS,
        default=None,
        help="Limit to a single source id (default: all).",
    )
    args = parser.parse_args()
    result = run(root=PROJECT_ROOT, source_id=args.source)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
