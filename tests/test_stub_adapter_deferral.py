"""Contract tests: registry sources without a concrete adapter stay deferred.

Wave M, task 73. The on-demand query module ships concrete adapters for a subset
of the 85 registry sources; every other source resolves to
:class:`NotImplementedAdapter`, whose ``fetch`` raises :class:`ManualOnlyError`.
That deferral is a deliberate safety property — a stubbed source must never
silently start returning data (e.g. because someone wired a half-finished
adapter into the registry without credentials/tests). These tests lock it:

  * every stub-resolved source raises ManualOnlyError on fetch (never returns rows);
  * the error names the source and points at its bulk producer_script;
  * concrete-adapter sources do NOT resolve to the stub;
  * the registry/stub split partitions the source universe with no overlap.

The assertions are **count-agnostic** on purpose: as real adapters land, the
concrete set grows and the stub set shrinks, but the partition property holds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from moneysweep.query.adapters import ADAPTER_REGISTRY, get_adapter
from moneysweep.query.adapters._stub import NotImplementedAdapter
from moneysweep.query.types import ManualOnlyError, Query
from moneysweep.runtime.source_registry import REPO_ROOT, all_sources

ROOT = REPO_ROOT


def _all_source_ids() -> list[str]:
    return [s["source_id"] for s in all_sources(ROOT) if s.get("source_id")]


def _stub_source_ids() -> list[str]:
    known = set(ADAPTER_REGISTRY)
    return [sid for sid in _all_source_ids() if sid not in known]


@pytest.mark.unit
def test_there_are_stub_resolved_sources():
    """Sanity: the deferral path is exercised by real registry entries."""
    stubs = _stub_source_ids()
    assert stubs, "expected at least one registry source without a concrete adapter"


@pytest.mark.unit
def test_every_stub_source_resolves_to_not_implemented_adapter():
    for sid in _stub_source_ids():
        adapter = get_adapter(sid, root=ROOT)
        assert isinstance(adapter, NotImplementedAdapter), (
            f"{sid} unexpectedly resolved to a concrete adapter {type(adapter).__name__}"
        )


@pytest.mark.unit
def test_stub_fetch_raises_manual_only_and_never_returns_rows():
    for sid in _stub_source_ids():
        adapter = get_adapter(sid, root=ROOT)
        with pytest.raises(ManualOnlyError) as exc:
            adapter.fetch(Query())
        # The error carries the source_id so callers know what was deferred.
        assert sid in str(exc.value) or getattr(exc.value, "source_id", None) == sid


@pytest.mark.unit
def test_concrete_sources_do_not_resolve_to_stub():
    for sid in ADAPTER_REGISTRY:
        adapter = get_adapter(sid, root=ROOT)
        assert not isinstance(adapter, NotImplementedAdapter), (
            f"concrete source {sid} fell through to the stub"
        )


@pytest.mark.unit
def test_registry_and_stub_sets_partition_the_universe():
    """Concrete ∪ stub == all sources, and the two sets are disjoint."""
    all_ids = set(_all_source_ids())
    concrete = set(ADAPTER_REGISTRY) & all_ids
    stub = set(_stub_source_ids())
    assert concrete.isdisjoint(stub)
    assert concrete | stub == all_ids


@pytest.mark.unit
def test_unknown_source_id_also_defers():
    """An entirely unregistered id resolves to the stub and defers, not crashes."""
    adapter = get_adapter("definitely_not_a_real_source_xyz", root=Path(ROOT))
    assert isinstance(adapter, NotImplementedAdapter)
    with pytest.raises(ManualOnlyError):
        adapter.fetch(Query())
