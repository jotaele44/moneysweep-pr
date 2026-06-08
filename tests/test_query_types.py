"""Tests for the Query / QueryResult / exception types."""

from __future__ import annotations

import pandas as pd
import pytest

from contract_sweeper.query.types import (
    CredentialMissing,
    ManualOnlyError,
    Query,
    QueryResult,
    SourceQueryOutcome,
)


@pytest.mark.unit
def test_query_hash_is_order_insensitive_for_municipalities():
    a = Query(municipalities=("San Juan", "Bayamón"))
    b = Query(municipalities=("Bayamón", "San Juan"))
    assert a.canonical_hash() == b.canonical_hash()


@pytest.mark.unit
def test_query_hash_is_order_insensitive_for_fiscal_years():
    a = Query(fiscal_years=(2024, 2023, 2022))
    b = Query(fiscal_years=(2022, 2024, 2023))
    assert a.canonical_hash() == b.canonical_hash()


@pytest.mark.unit
def test_query_hash_dedupes_inputs():
    a = Query(municipalities=("San Juan", "San Juan"))
    b = Query(municipalities=("San Juan",))
    assert a.canonical_hash() == b.canonical_hash()


@pytest.mark.unit
def test_query_hash_changes_with_different_inputs():
    a = Query(municipalities=("San Juan",))
    b = Query(municipalities=("Ponce",))
    assert a.canonical_hash() != b.canonical_hash()


@pytest.mark.unit
def test_query_canonical_dict_shape():
    q = Query(
        municipalities=("Ponce", "San Juan"),
        fiscal_years=(2024, 2023),
        date_range=("2023-01-01", "2024-12-31"),
        agencies=("DHS",),
        recipient_ueis=("ABC123",),
    )
    d = q.canonical_dict()
    assert d == {
        "municipalities": ["Ponce", "San Juan"],
        "fiscal_years": [2023, 2024],
        "date_range": ["2023-01-01", "2024-12-31"],
        "agencies": ["DHS"],
        "recipient_ueis": ["ABC123"],
    }


@pytest.mark.unit
def test_query_result_combined_concatenates_with_source_id():
    q = Query(municipalities=("San Juan",))
    result = QueryResult(query=q)
    result.outcomes["a"] = SourceQueryOutcome(
        source_id="a", status="ok", df=pd.DataFrame({"x": [1, 2]}), rows=2
    )
    result.outcomes["b"] = SourceQueryOutcome(
        source_id="b", status="cache_hit", df=pd.DataFrame({"x": [3]}), rows=1
    )
    result.outcomes["c"] = SourceQueryOutcome(source_id="c", status="manual_only")
    combined = result.combined
    assert len(combined) == 3
    assert set(combined["source_id"].unique()) == {"a", "b"}


@pytest.mark.unit
def test_query_result_summary_counts():
    q = Query()
    result = QueryResult(query=q)
    result.outcomes["a"] = SourceQueryOutcome(source_id="a", status="ok", rows=10)
    result.outcomes["b"] = SourceQueryOutcome(source_id="b", status="cache_hit", rows=5)
    result.outcomes["c"] = SourceQueryOutcome(source_id="c", status="manual_only")
    result.outcomes["d"] = SourceQueryOutcome(source_id="d", status="error", error="boom")
    s = result.summary()
    assert s["ok"] == 1
    assert s["cache_hit"] == 1
    assert s["manual_only"] == 1
    assert s["error"] == 1
    assert s["total_rows"] == 15


@pytest.mark.unit
def test_manual_only_error_carries_structured_payload():
    exc = ManualOnlyError(
        source_id="lda",
        producer_script="scripts/download_lda.py",
        authentication="manual_export",
    )
    assert exc.source_id == "lda"
    assert "scripts/download_lda.py" in str(exc)
    assert "manual_export" in str(exc)


@pytest.mark.unit
def test_credential_missing_carries_env_var():
    exc = CredentialMissing("fec", "FEC_API_KEY")
    assert exc.env_var == "FEC_API_KEY"
    assert "FEC_API_KEY" in str(exc)
