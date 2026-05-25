"""Tests for the dispatcher's caching, error handling, and source routing."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from contract_sweeper.query import Query, query
from contract_sweeper.query.adapters import ADAPTER_REGISTRY
from contract_sweeper.query.adapters.base import SourceAdapter

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
    # 'lda' has no concrete adapter — must report manual_only without raising.
    r = query(Query(municipalities=("San Juan",)), source_ids=["lda"], root=tmp_path)
    assert r.outcomes["lda"].status == "manual_only"
    assert r.outcomes["lda"].df is None
    assert "download_lda.py" in (r.outcomes["lda"].reason or "")


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
            source_ids=["usaspending_prime", "lda"],
            root=tmp_path,
        )
    assert r.outcomes["usaspending_prime"].status == "ok"
    assert r.outcomes["lda"].status == "manual_only"
    combined = r.combined
    # Only the ok outcome contributes rows.
    assert (combined["source_id"] == "usaspending_prime").all()


@pytest.mark.unit
def test_dispatcher_default_source_ids_includes_concrete_adapters(tmp_path):
    """When source_ids is None, query() consults every registered adapter."""
    _StaticAdapter.call_count = 0
    fake_openfema = MagicMock(spec=SourceAdapter)
    fake_openfema.source_id = "fema_pa_openfema_v2"
    fake_openfema.fetch.return_value = pd.DataFrame({"countyFips": ["72127"]})
    fake_fec_cls = MagicMock(return_value=fake_openfema)

    # Replace OpenFEMA adapter class with a stub that returns an instance.
    class _OFA(SourceAdapter):
        source_id = "fema_pa_openfema_v2"

        def fetch(self, q):
            return pd.DataFrame({"countyFips": ["72127"]})

    class _FEC(SourceAdapter):
        source_id = "fec"

        def fetch(self, q):
            return pd.DataFrame({"contributor_city": ["SAN JUAN"]})

    with patch.dict(
        ADAPTER_REGISTRY,
        {
            "usaspending_prime": _StaticAdapter,
            "fema_pa_openfema_v2": _OFA,
            "fec": _FEC,
        },
        clear=False,
    ):
        r = query(Query(), root=tmp_path)
    # All three concrete adapters must appear in outcomes.
    assert set(r.outcomes.keys()) == {"usaspending_prime", "fema_pa_openfema_v2", "fec"}
    assert all(o.status == "ok" for o in r.outcomes.values())
