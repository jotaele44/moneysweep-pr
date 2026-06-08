"""Tests for the on-demand query FileCache."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from contract_sweeper.query.cache import FileCache, ttl_for_cadence
from contract_sweeper.query.types import Query


@pytest.fixture
def cache(tmp_path: Path) -> FileCache:
    return FileCache(tmp_path)


@pytest.fixture
def sample_query() -> Query:
    return Query(municipalities=("San Juan",), fiscal_years=(2024,))


@pytest.mark.unit
def test_ttl_for_cadence_known_cadences():
    assert ttl_for_cadence("weekly") == 7 * 86_400
    assert ttl_for_cadence("monthly") == 30 * 86_400
    assert ttl_for_cadence("quarterly") == 90 * 86_400
    assert ttl_for_cadence("Yearly") == 365 * 86_400


@pytest.mark.unit
def test_ttl_for_cadence_unknown_falls_back_to_default():
    assert ttl_for_cadence(None) == 7 * 86_400
    assert ttl_for_cadence("never") == 7 * 86_400


@pytest.mark.unit
def test_get_returns_none_when_no_entry(cache, sample_query):
    assert cache.get("usaspending_prime", sample_query.canonical_hash(), ttl_seconds=3600) is None


@pytest.mark.unit
def test_put_then_get_roundtrip(cache, sample_query):
    df = pd.DataFrame({"award_id": ["1", "2"], "amount": ["10", "20"]})
    cache.put(
        "usaspending_prime", sample_query.canonical_hash(), df, query=sample_query, ttl_seconds=3600
    )
    hit = cache.get("usaspending_prime", sample_query.canonical_hash(), ttl_seconds=3600)
    assert hit is not None
    out_df, meta = hit
    assert list(out_df["award_id"]) == ["1", "2"]
    assert meta["row_count"] == 2
    assert "sha256" in meta
    assert meta["query"]["municipalities"] == ["San Juan"]


@pytest.mark.unit
def test_get_returns_none_when_entry_is_expired(cache, sample_query, tmp_path):
    df = pd.DataFrame({"x": ["1"]})
    cache.put("s", sample_query.canonical_hash(), df, query=sample_query, ttl_seconds=3600)
    # Mutate the sidecar to backdate `fetched_at` past the TTL.
    sidecar = tmp_path / "data" / "cache" / "s" / f"{sample_query.canonical_hash()}.manifest.json"
    meta = json.loads(sidecar.read_text())
    meta["fetched_at"] = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat()
    sidecar.write_text(json.dumps(meta))
    assert cache.get("s", sample_query.canonical_hash(), ttl_seconds=3600) is None


@pytest.mark.unit
def test_get_with_corrupt_sidecar_returns_none(cache, sample_query, tmp_path):
    df = pd.DataFrame({"x": ["1"]})
    cache.put("s", sample_query.canonical_hash(), df, query=sample_query, ttl_seconds=3600)
    sidecar = tmp_path / "data" / "cache" / "s" / f"{sample_query.canonical_hash()}.manifest.json"
    sidecar.write_text("not json {")
    assert cache.get("s", sample_query.canonical_hash(), ttl_seconds=3600) is None


@pytest.mark.unit
def test_put_creates_source_subdirectory(cache, sample_query, tmp_path):
    df = pd.DataFrame({"x": ["1"]})
    cache.put(
        "a_brand_new_source",
        sample_query.canonical_hash(),
        df,
        query=sample_query,
        ttl_seconds=3600,
    )
    assert (tmp_path / "data" / "cache" / "a_brand_new_source").is_dir()


@pytest.mark.unit
def test_put_writes_parquet_body_and_sidecar(cache, sample_query, tmp_path):
    df = pd.DataFrame({"x": ["1"]})
    cache.put("s", sample_query.canonical_hash(), df, query=sample_query, ttl_seconds=3600)
    h = sample_query.canonical_hash()
    body = tmp_path / "data" / "cache" / "s" / f"{h}.parquet"
    sidecar = tmp_path / "data" / "cache" / "s" / f"{h}.manifest.json"
    assert body.exists()
    assert sidecar.exists()
