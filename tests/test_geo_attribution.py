"""Tests for the PR geographic attribution layer."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from moneysweep.runtime.geo_attribution import (
    GEO_COLUMNS,
    attribute_geo,
    attribution_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def _row(df: pd.DataFrame, i: int) -> dict:
    return {col: df.iloc[i][col] for col in df.columns}


@pytest.mark.unit
def test_reference_table_has_78_rows_with_unique_codes():
    path = REPO_ROOT / "data" / "reference" / "pr_municipalities.csv"
    ref = pd.read_csv(path, dtype=str)
    assert len(ref) == 78
    codes = ref["municipality_code"].tolist()
    assert len(set(codes)) == 78
    # Every row carries a non-empty aliases list.
    assert (ref["aliases"].astype(str).str.len() > 0).all()


@pytest.mark.unit
def test_exact_name_san_juan_matches_72127():
    df = pd.DataFrame({"municipality": ["San Juan"]})
    out = attribute_geo(df, root=REPO_ROOT)
    row = _row(out, 0)
    assert row["geo_municipality_code"] == "72127"
    assert row["geo_municipality_name"] == "San Juan"
    assert row["geo_attribution_confidence"] == "exact_name"
    assert row["geo_attribution_source"] == "municipality"


@pytest.mark.unit
def test_normalized_name_municipio_de_bayamon_matches_72021():
    df = pd.DataFrame({"municipality": ["Municipio de Bayamón"]})
    out = attribute_geo(df, root=REPO_ROOT)
    row = _row(out, 0)
    assert row["geo_municipality_code"] == "72021"
    assert row["geo_attribution_confidence"] == "normalized_name"


@pytest.mark.unit
def test_exact_fips_beats_name():
    df = pd.DataFrame({"county_fips": ["72127"], "municipality": ["Wrong Name"]})
    out = attribute_geo(df, root=REPO_ROOT)
    row = _row(out, 0)
    assert row["geo_municipality_code"] == "72127"
    assert row["geo_attribution_confidence"] == "exact_fips"
    assert row["geo_attribution_source"] == "county_fips"


@pytest.mark.unit
def test_diacritics_collapse_mayaguez():
    accented = pd.DataFrame({"municipality": ["Mayagüez"]})
    plain = pd.DataFrame({"municipality": ["Mayaguez"]})
    a = attribute_geo(accented, root=REPO_ROOT)
    b = attribute_geo(plain, root=REPO_ROOT)
    assert a.iloc[0]["geo_municipality_code"] == "72097"
    assert b.iloc[0]["geo_municipality_code"] == "72097"


@pytest.mark.unit
def test_unknown_municipality_preserved_with_unknown_confidence():
    df = pd.DataFrame({"municipality": ["Atlantis", "San Juan"]})
    out = attribute_geo(df, root=REPO_ROOT)
    assert len(out) == 2  # never drops rows
    assert out.iloc[0]["geo_municipality_code"] == ""
    assert out.iloc[0]["geo_attribution_confidence"] == "unknown"
    assert out.iloc[1]["geo_municipality_code"] == "72127"


@pytest.mark.unit
def test_idempotent_attribute_geo():
    df = pd.DataFrame({"municipality": ["San Juan", "Bayamón"]})
    once = attribute_geo(df, root=REPO_ROOT)
    twice = attribute_geo(once, root=REPO_ROOT)
    # Same shape, same geo columns, same values.
    assert list(once.columns) == list(twice.columns)
    for col in GEO_COLUMNS:
        assert once[col].tolist() == twice[col].tolist()


@pytest.mark.unit
def test_pop_county_field_is_recognized_as_geo_input():
    # pop_county is the canonical alias used by USAspending downloaders.
    df = pd.DataFrame({"pop_county": ["PONCE"]})
    out = attribute_geo(df, root=REPO_ROOT)
    row = _row(out, 0)
    assert row["geo_municipality_code"] == "72113"
    assert row["geo_attribution_source"] == "pop_county"


@pytest.mark.unit
def test_place_of_performance_city_field_is_recognized():
    df = pd.DataFrame({"place_of_performance_city": ["CAGUAS"]})
    out = attribute_geo(df, root=REPO_ROOT)
    assert out.iloc[0]["geo_municipality_code"] == "72025"


@pytest.mark.unit
def test_empty_dataframe_returns_geo_columns():
    df = pd.DataFrame(columns=["municipality"])
    out = attribute_geo(df, root=REPO_ROOT)
    for col in GEO_COLUMNS:
        assert col in out.columns


@pytest.mark.unit
def test_zip_and_latlon_passthrough_when_present():
    df = pd.DataFrame(
        {
            "municipality": ["San Juan"],
            "zip_code": ["00901"],
            "latitude": ["18.4655"],
            "longitude": ["-66.1057"],
        }
    )
    out = attribute_geo(df, root=REPO_ROOT)
    row = _row(out, 0)
    assert row["geo_zip"] == "00901"
    assert row["geo_lat"] == "18.4655"
    assert row["geo_lon"] == "-66.1057"


@pytest.mark.unit
def test_attribution_summary_counts_buckets():
    df = pd.DataFrame({"municipality": ["San Juan", "Atlantis", "Municipio de Ponce"]})
    out = attribute_geo(df, root=REPO_ROOT)
    summary = attribution_summary(out)
    assert summary["total"] == 3
    assert summary["unknown"] == 1
    assert summary["attributed"] == 2
    assert summary["exact_name"] == 1
    assert summary["normalized_name"] == 1


@pytest.mark.unit
def test_fips_with_trailing_dot_zero_still_resolves():
    # USAspending dumps sometimes carry FIPS as floats serialized to text.
    df = pd.DataFrame({"county_fips": ["72127.0"]})
    out = attribute_geo(df, root=REPO_ROOT)
    assert out.iloc[0]["geo_municipality_code"] == "72127"
    assert out.iloc[0]["geo_attribution_confidence"] == "exact_fips"


@pytest.mark.unit
def test_non_pr_fips_does_not_match():
    df = pd.DataFrame({"county_fips": ["48201"]})  # Harris County, TX
    out = attribute_geo(df, root=REPO_ROOT)
    assert out.iloc[0]["geo_municipality_code"] == ""
    assert out.iloc[0]["geo_attribution_confidence"] == "unknown"
