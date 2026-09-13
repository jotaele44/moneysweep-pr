"""Coverage-gap intake — deferred producer (intentionally not implemented).

Registered ``producer_script`` for a P1 financial source promoted from the
coverage-gap backlog (``reports/financial_source_coverage_gaps.md``) into the
registry as a tracked intake stub:

  - ``pr_act_154_excise``          Act 154 excise on foreign controlled corporations (scraper surface)

(``census_gov_finances`` and ``fta_ntd`` graduated to real producers —
``scripts/download_census_gov_finances.py`` and ``scripts/download_fta_ntd.py``.
``hacienda_sut_ivu`` graduated the same way — ``scripts/download_hacienda_sut_ivu.py`` —
once direct testing showed hacienda.pr.gov *is* reachable with no key required; this
module's "no network egress" premise did not hold for that source. ``pr_act_154_excise``
remains here because no Hacienda page matching the described $1.8B/yr foreign-controlled-
corporation excise line has been identified yet — see README's queued-sources note. That is
a source-discovery gap, not an environment/egress one, and needs its own investigation
before a real adapter can be written; guessing at a page and parsing it blind is exactly
the failure mode this stub avoids.)

Like ``scripts/download_nara_nextgen.py``, declaring this producer keeps the
readiness preflight honest: each source resolves to a real, importable, callable
producer instead of a fatal ``missing_producer`` structural error, while ``run``
performs no network I/O and materializes nothing — so the source correctly remains
``not_materialized`` until its source page is identified and a real adapter is built.

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
COVERAGE_GAP_SOURCE_IDS = ("pr_act_154_excise",)


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
            f"[coverage_gap_intake] {sid}: source page not yet identified — no adapter "
            f"built. Skipping (0 rows, not_materialized)."
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
