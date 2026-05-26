"""Shared post-ingest enrichment for every source in the registry.

Every producer (a `scripts/download_*.py` / `scripts/ingest_*.py` /
`scripts/build_*.py`) should call `apply_post_ingest()` on its dataframe
immediately before writing the registry-declared `expected_outputs`. The
backfill script (`scripts/backfill_geo_attribution.py`) applies the same
function to files already on disk.

Currently the only enrichment step is geographic attribution (PR municipality
FIPS attached on a canonical schema). Future steps (entity normalization,
currency canonicalization) hook in here so producers never need to know
about them.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from contract_sweeper.runtime.geo_attribution import attribute_geo


def apply_post_ingest(
    df: pd.DataFrame,
    *,
    source_id: str,
    root: Path | None = None,
) -> pd.DataFrame:
    """Run every post-ingest enrichment step on `df`.

    Currently:
        * geo attribution via :func:`attribute_geo`

    Idempotent: re-running on an already-enriched dataframe is a no-op for
    rows that were successfully attributed.
    """
    if df is None or len(df) == 0:
        return attribute_geo(df, source_id=source_id, root=root)
    return attribute_geo(df, source_id=source_id, root=root)
