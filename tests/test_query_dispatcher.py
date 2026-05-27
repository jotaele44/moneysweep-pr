"""Tests for the dispatcher's caching, error handling, and source routing."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from contract_sweeper.query import (
    EntityIdentifier,
    EntityQuery,
    Query,
    query,
    query_entities,
)
from contract_sweeper.query.adapters import ADAPTER_REGISTRY, ENTITY_ADAPTER_REGISTRY
from contract_sweeper.query.adapters.base import SourceAdapter
from contract_sweeper.query.adapters.entity_base import EntityAdapter
from contract_sweeper.query.types import CredentialMissing

REPO_ROOT = Path(__file__).resolve().parents[1]


class _StaticAdapter(SourceAdapter):
    """Test-only adapter that returns a fixed DataFrame and counts fetch calls."""

    source_id = "usaspending_prime"
    call_count = 0

    def fetch(self, q: Query) -> pd.DataFrame:
        type(self).call_count += 1
        return pd.DataFrame({"municipality": ["San Juan"], "amount": ["100"]})


@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Force every dispatcher test to write its cache under a tmp root."""
    # The dispatcher resolves root via Path(root) if root else REPO_ROOT,
    # so just pass tmp_path-rooted reference symlinks to the real ref table.
    ref_dir = tmp_path / "data" / "reference"
    ref_dir.mkdir(parents=True)
    real_ref = REPO_ROOT / "data" / "reference" / "pr_municipalities.csv"
    (ref_dir / "pr_municipalities.csv").write_bytes(real_ref.read_bytes())
    # Symlink registry so source_by_id resolves under tmp_path.
    reg_dir = tmp_path / "registries"
    reg_dir.mkdir()
    for f in ("source_registry.json", "schema_registry.json"):
        (reg_dir / f).write_bytes((REPO_ROOT / "registries" / f).read_bytes())
    yield tmp_path


@pytest.mark.unit
def test_dispatcher_returns_manual_only_for_stubbed_source(tmp_path):
    # 'sam_entities' has no concrete adapter — must report manual_only without raising.
    r = query(Query(municipalities=("San Juan",)), source_ids=["sam_entities"], root=tmp_path)
    assert r.outcomes["sam_entities"].status == "manual_only"
    assert r.outcomes["sam_entities"].df is None
    assert "sam_enrichment.py" in (r.outcomes["sam_entities"].reason or "")


@pytest.mark.unit
def test_dispatcher_cache_miss_then_hit(tmp_path):
    _StaticAdapter.call_count = 0
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        r1 = query(Query(municipalities=("San Juan",), fiscal_years=(2024,)),
                   source_ids=["usaspending_prime"], root=tmp_path)
        r2 = query(Query(municipalities=("San Juan",), fiscal_years=(2024,)),
                   source_ids=["usaspending_prime"], root=tmp_path)
    assert r1.outcomes["usaspending_prime"].status == "ok"
    assert r2.outcomes["usaspending_prime"].status == "cache_hit"
    # Adapter was only invoked once across the two queries.
    assert _StaticAdapter.call_count == 1
    # cache_hit and ok return the same row data.
    assert len(r1.outcomes["usaspending_prime"].df) == 1
    assert len(r2.outcomes["usaspending_prime"].df) == 1


@pytest.mark.unit
def test_dispatcher_force_refresh_skips_cache(tmp_path):
    _StaticAdapter.call_count = 0
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        q = Query(municipalities=("San Juan",), fiscal_years=(2024,))
        query(q, source_ids=["usaspending_prime"], root=tmp_path)
        query(q, source_ids=["usaspending_prime"], root=tmp_path, force_refresh=True)
    assert _StaticAdapter.call_count == 2


@pytest.mark.unit
def test_dispatcher_records_error_when_adapter_raises(tmp_path):
    class _BrokenAdapter(SourceAdapter):
        source_id = "usaspending_prime"

        def fetch(self, q):
            raise RuntimeError("upstream 500")

    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _BrokenAdapter}, clear=False):
        r = query(Query(), source_ids=["usaspending_prime"], root=tmp_path)
    assert r.outcomes["usaspending_prime"].status == "error"
    assert "upstream 500" in (r.outcomes["usaspending_prime"].error or "")


@pytest.mark.unit
def test_dispatcher_attaches_geo_columns_via_post_ingest(tmp_path):
    _StaticAdapter.call_count = 0
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        r = query(Query(municipalities=("San Juan",)),
                  source_ids=["usaspending_prime"], root=tmp_path)
    df = r.outcomes["usaspending_prime"].df
    assert "geo_municipality_code" in df.columns
    assert df.iloc[0]["geo_municipality_code"] == "72127"


@pytest.mark.unit
def test_dispatcher_mixed_query_partial_success(tmp_path):
    _StaticAdapter.call_count = 0
    with patch.dict(ADAPTER_REGISTRY, {"usaspending_prime": _StaticAdapter}, clear=False):
        r = query(
            Query(municipalities=("San Juan",)),
            source_ids=["usaspending_prime", "sam_entities"],
            root=tmp_path,
        )
    assert r.outcomes["usaspending_prime"].status == "ok"
    assert r.outcomes["sam_entities"].status == "manual_only"
    combined = r.combined
    # Only the ok outcome contributes rows.
    assert (combined["source_id"] == "usaspending_prime").all()


@pytest.mark.unit
def test_dispatcher_default_source_ids_includes_concrete_adapters(tmp_path):
    """When source_ids is None, query() consults every registered adapter."""
    _StaticAdapter.call_count = 0

    class _StubReturn(SourceAdapter):
        """Stand-in that returns an empty DataFrame — used to neutralize live HTTP."""

        source_id = ""

        def fetch(self, q):
            return pd.DataFrame()

    # Patch every concrete adapter to a benign stub so no real HTTP runs.
    patched = {sid: _StubReturn for sid in ADAPTER_REGISTRY.keys()}
    patched["usaspending_prime"] = _StaticAdapter
    with patch.dict(ADAPTER_REGISTRY, patched, clear=False):
        r = query(Query(), root=tmp_path)

    # Every concrete adapter source_id must appear in outcomes.
    assert set(r.outcomes.keys()).issuperset(set(ADAPTER_REGISTRY.keys()))
    # The one with real-looking data should be 'ok'; the empty-DF stubs are also 'ok'.
    assert r.outcomes["usaspending_prime"].status == "ok"
    assert r.outcomes["usaspending_prime"].rows == 1


# ---------------------------------------------------------------------------
# Entity-mode dispatcher tests
# ---------------------------------------------------------------------------


class _StaticEntityAdapter(EntityAdapter):
    source_id = "sam_entities"
    supported_kinds = frozenset({"uei", "name"})
    call_count = 0

    def fetch(self, q):
        type(self).call_count += 1
        return pd.DataFrame([{"uei": "X1", "legal_business_name": "Stub Co"}])


class _CredMissingEntityAdapter(EntityAdapter):
    source_id = "sam_entities"
    supported_kinds = frozenset({"uei"})

    def fetch(self, q):
        raise CredentialMissing("sam_entities", "SAM_API_KEY")


class _RaisingEntityAdapter(EntityAdapter):
    source_id = "ofac_sdn"
    supported_kinds = frozenset({"name"})

    def fetch(self, q):
        raise RuntimeError("boom")


@pytest.mark.unit
def test_query_entities_dispatches_to_registered_adapter(tmp_path):
    _StaticEntityAdapter.call_count = 0
    with patch.dict(ENTITY_ADAPTER_REGISTRY, {"sam_entities": _StaticEntityAdapter}, clear=False):
        eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="X1"),))
        r = query_entities(eq, source_ids=["sam_entities"], root=tmp_path)
    out = r.outcomes["sam_entities"]
    assert out.status == "ok"
    assert out.rows == 1
    assert _StaticEntityAdapter.call_count == 1


@pytest.mark.unit
def test_query_entities_caches_results(tmp_path):
    """Second call with the same EntityQuery hits the cache, not the adapter."""
    _StaticEntityAdapter.call_count = 0
    with patch.dict(ENTITY_ADAPTER_REGISTRY, {"sam_entities": _StaticEntityAdapter}, clear=False):
        eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="X1"),))
        first = query_entities(eq, source_ids=["sam_entities"], root=tmp_path)
        second = query_entities(eq, source_ids=["sam_entities"], root=tmp_path)
    assert first.outcomes["sam_entities"].status == "ok"
    assert second.outcomes["sam_entities"].status == "cache_hit"
    assert _StaticEntityAdapter.call_count == 1


@pytest.mark.unit
def test_query_entities_unknown_source_returns_manual_only(tmp_path):
    eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="X1"),))
    r = query_entities(eq, source_ids=["totally_unregistered"], root=tmp_path)
    out = r.outcomes["totally_unregistered"]
    assert out.status == "manual_only"
    assert "no entity-mode adapter" in (out.reason or "")


@pytest.mark.unit
def test_query_entities_credential_missing_surfaces_as_error(tmp_path):
    with patch.dict(
        ENTITY_ADAPTER_REGISTRY, {"sam_entities": _CredMissingEntityAdapter}, clear=False
    ):
        eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="X1"),))
        r = query_entities(eq, source_ids=["sam_entities"], root=tmp_path)
    out = r.outcomes["sam_entities"]
    assert out.status == "error"
    assert "SAM_API_KEY" in (out.error or "")


@pytest.mark.unit
def test_query_entities_error_isolation(tmp_path):
    """One adapter raising must not interrupt the rest."""
    _StaticEntityAdapter.call_count = 0
    with patch.dict(
        ENTITY_ADAPTER_REGISTRY,
        {"sam_entities": _StaticEntityAdapter, "ofac_sdn": _RaisingEntityAdapter},
        clear=False,
    ):
        eq = EntityQuery(identifiers=(
            EntityIdentifier(kind="uei", value="X1"),
            EntityIdentifier(kind="name", value="Acme"),
        ))
        r = query_entities(eq, source_ids=["sam_entities", "ofac_sdn"], root=tmp_path)
    assert r.outcomes["sam_entities"].status == "ok"
    assert r.outcomes["ofac_sdn"].status == "error"
    assert "boom" in (r.outcomes["ofac_sdn"].error or "")


@pytest.mark.unit
def test_query_entities_default_source_ids_covers_entity_registry(tmp_path):
    """When source_ids is None, dispatch hits every registered entity source."""
    class _Empty(EntityAdapter):
        source_id = ""
        supported_kinds = frozenset()

        def fetch(self, q):
            return pd.DataFrame()

    patched = {sid: _Empty for sid in ENTITY_ADAPTER_REGISTRY.keys()}
    with patch.dict(ENTITY_ADAPTER_REGISTRY, patched, clear=False):
        eq = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="X1"),))
        r = query_entities(eq, root=tmp_path)
    assert set(r.outcomes.keys()) == set(ENTITY_ADAPTER_REGISTRY.keys())

