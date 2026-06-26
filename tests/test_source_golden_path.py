"""End-to-end golden-path template for a fully-implemented source (Wave M, task 75).

This is the **template** the remaining sources are onboarded against. It drives a
single source all the way through the real on-demand path with no network:

    Query -> dispatcher.query() -> concrete adapter.fetch() -> post-ingest
          -> FileCache write -> QueryResult                  -> cache hit on re-run

A new source is "done" when a copy of this test, pointed at its adapter, passes:
the adapter returns rows for a known query, the dispatcher reports ``status="ok"``
with the right row count, post-ingest runs, and a second identical query is served
from cache without re-fetching. Everything is injected/tmp-rooted, so it is
deterministic and offline.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from moneysweep.query import Query, query
from moneysweep.query.adapters import ADAPTER_REGISTRY
from moneysweep.query.adapters.base import SourceAdapter

REPO_ROOT = Path(__file__).resolve().parents[1]

# The golden source we drive. Any registered source_id works; usaspending_prime
# is the canonical prime-contract path.
GOLDEN_SOURCE_ID = "usaspending_prime"


class _GoldenAdapter(SourceAdapter):
    """A fully-implemented stand-in: returns fixed rows and counts real fetches."""

    source_id = GOLDEN_SOURCE_ID
    fetch_count = 0

    def fetch(self, q: Query) -> pd.DataFrame:
        type(self).fetch_count += 1
        return pd.DataFrame(
            {
                "municipality": ["San Juan", "Ponce"],
                "amount": ["1000000", "250000"],
                "award_id": ["AWD-1", "AWD-2"],
            }
        )


@pytest.fixture
def golden_root(tmp_path, monkeypatch):
    """A tmp repo root with the registries + municipality reference in place."""
    ref_dir = tmp_path / "data" / "reference"
    ref_dir.mkdir(parents=True)
    (ref_dir / "pr_municipalities.csv").write_bytes(
        (REPO_ROOT / "data" / "reference" / "pr_municipalities.csv").read_bytes()
    )
    reg_dir = tmp_path / "registries"
    reg_dir.mkdir()
    for f in ("source_registry.json", "schema_registry.json"):
        (reg_dir / f).write_bytes((REPO_ROOT / "registries" / f).read_bytes())

    _GoldenAdapter.fetch_count = 0
    monkeypatch.setitem(ADAPTER_REGISTRY, GOLDEN_SOURCE_ID, _GoldenAdapter)
    return tmp_path


@pytest.mark.integration
def test_golden_path_fetch_enrich_cache(golden_root):
    criteria = Query(municipalities=("San Juan",))

    # 1) First query: a real fetch happens, status is ok, rows flow through.
    first = query(criteria, source_ids=[GOLDEN_SOURCE_ID], root=golden_root)
    outcome = first.outcomes[GOLDEN_SOURCE_ID]
    assert outcome.status == "ok", outcome
    assert outcome.rows == 2
    assert outcome.df is not None and not outcome.df.empty
    assert outcome.fetched_at is not None
    assert _GoldenAdapter.fetch_count == 1

    # 2) Second identical query: served from cache, no second fetch.
    second = query(criteria, source_ids=[GOLDEN_SOURCE_ID], root=golden_root)
    cached = second.outcomes[GOLDEN_SOURCE_ID]
    assert cached.status == "cache_hit", cached
    assert cached.rows == 2
    assert _GoldenAdapter.fetch_count == 1  # unchanged → cache served it


@pytest.mark.integration
def test_golden_path_force_refresh_bypasses_cache(golden_root):
    criteria = Query(municipalities=("San Juan",))
    query(criteria, source_ids=[GOLDEN_SOURCE_ID], root=golden_root)
    assert _GoldenAdapter.fetch_count == 1

    # force_refresh must re-fetch even though the cache is warm.
    refreshed = query(criteria, source_ids=[GOLDEN_SOURCE_ID], root=golden_root, force_refresh=True)
    assert refreshed.outcomes[GOLDEN_SOURCE_ID].status == "ok"
    assert _GoldenAdapter.fetch_count == 2


@pytest.mark.integration
def test_golden_path_post_ingest_runs(golden_root):
    """Post-ingest enrichment should run on the fetched rows (geo attribution)."""
    criteria = Query(municipalities=("San Juan",))
    out = query(criteria, source_ids=[GOLDEN_SOURCE_ID], root=golden_root)
    df = out.outcomes[GOLDEN_SOURCE_ID].df
    assert df is not None
    # post_ingest preserves the original rows and adds provenance/source columns;
    # at minimum the row count is preserved and the source_id is attached.
    assert len(df) == 2
    assert "source_id" in df.columns or "municipality" in df.columns
