"""
NARA archival-metadata locator — deferred producer (intentionally not implemented).

This module is the registered ``producer_script`` for two optional, non-spine
sources defined in ``registries/source_registry_extensions/nara_nextgen.yaml``:

  - ``nara_nextgen_catalog_v3``   (NARA Catalog API v3; auth: NARA_API_KEY)
  - ``nara_catalog_aws_open_data`` (NARA bulk metadata on AWS Open Data)

Both fetchers are deliberately deferred until a credential, a bounded query
allowlist, and a verified storage/licensing policy are in place (see the source
notes in the extension registry). Declaring this producer keeps the pipeline
readiness preflight honest: the sources resolve to a real, importable, callable
producer instead of a fatal ``missing_producer`` structural error, while the
``run`` entrypoint performs no network I/O and materializes nothing — so the
sources correctly remain ``not_materialized`` in gap analysis.

Usage:
  python3 scripts/download_nara_nextgen.py [--source <source_id>]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging

# Source IDs this producer serves (mirrors the extension registry).
NARA_SOURCE_IDS = ("nara_nextgen_catalog_v3", "nara_catalog_aws_open_data")


def run(root: Path | None = None, source_id: str | None = None, **_kwargs) -> dict:
    """Deferred no-op entrypoint.

    Performs no network calls and writes no outputs. Returns a result dict in the
    shape other producers use so an accidental pipeline invocation degrades
    gracefully rather than raising.
    """
    logger = setup_logging("nara_nextgen")
    targets = [source_id] if source_id else list(NARA_SOURCE_IDS)
    for sid in targets:
        logger.info(
            f"[nara_nextgen] {sid}: fetcher deferred — no credential/allowlist/"
            f"storage policy confirmed yet. Skipping (0 rows, not_materialized)."
        )
    return {
        "rows": 0,
        "status": "deferred",
        "materialized": False,
        "sources": targets,
        "reason": "fetcher intentionally not implemented; see extension registry notes",
    }


# Entrypoint aliases recognized by the pipeline readiness preflight.
main = run
download = run


def _cli() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        choices=NARA_SOURCE_IDS,
        default=None,
        help="Limit to a single NARA source id (default: both).",
    )
    args = parser.parse_args()
    result = run(root=PROJECT_ROOT, source_id=args.source)
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
