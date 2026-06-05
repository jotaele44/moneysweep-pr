"""Tests for the additive post-ingest enrichment steps."""
import pandas as pd
import pytest

from contract_sweeper.runtime import post_ingest as pi


@pytest.mark.unit
def test_to_number_parses_money_strings():
    assert pi._to_number("$1,234.50") == 1234.50
    assert pi._to_number("(500)") == -500.0
    assert pi._to_number("") is None
    assert pi._to_number(None) is None
    assert pi._to_number("n/a") is None
    assert pi._to_number(float("nan")) is None


@pytest.mark.unit
def test_normalize_entities_adds_clustering_key():
    df = pd.DataFrame({"recipient_name": ["Acme Corp.", "Municipio de Ponce", None]})
    out = pi.normalize_entities(df)
    assert "entity_normalized" in out.columns
    assert out.loc[0, "entity_normalized"] == "ACME"  # legal suffix stripped
    assert out.loc[2, "entity_normalized"] == ""      # None -> empty


@pytest.mark.unit
def test_normalize_entities_idempotent_and_guarded():
    # No entity column → unchanged.
    df = pd.DataFrame({"unrelated": [1, 2]})
    assert "entity_normalized" not in pi.normalize_entities(df).columns
    # Existing column → not overwritten.
    df2 = pd.DataFrame({"recipient_name": ["X"], "entity_normalized": ["KEEP"]})
    assert pi.normalize_entities(df2).loc[0, "entity_normalized"] == "KEEP"


@pytest.mark.unit
def test_canonicalize_currency_is_additive_and_idempotent():
    df = pd.DataFrame({"obligated_amount": ["$1,000", "(2,500.00)", ""]})
    out = pi.canonicalize_currency(df)
    assert list(out["obligated_amount"]) == ["$1,000", "(2,500.00)", ""]  # source untouched
    assert out.loc[0, "obligated_amount_canonical"] == 1000.0
    assert out.loc[1, "obligated_amount_canonical"] == -2500.0
    assert pd.isna(out.loc[2, "obligated_amount_canonical"])
    # Idempotent: existing canonical column not recomputed.
    out2 = pi.canonicalize_currency(out)
    assert (out2["obligated_amount_canonical"].fillna(0) == out["obligated_amount_canonical"].fillna(0)).all()


@pytest.mark.unit
def test_apply_post_ingest_runs_all_steps(tmp_path):
    df = pd.DataFrame({
        "recipient_name": ["Acme Corp"],
        "obligated_amount": ["$5,000"],
        "recipient_city": ["San Juan"],
    })
    out = pi.apply_post_ingest(df, source_id="usaspending_prime", root=None)
    assert "entity_normalized" in out.columns
    assert out.loc[0, "obligated_amount_canonical"] == 5000.0
    # geo attribution still runs (canonical geo columns present)
    assert any(c.startswith("geo_") for c in out.columns)
