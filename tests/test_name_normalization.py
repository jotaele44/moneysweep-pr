"""Tests for the name-normalization helper."""
from __future__ import annotations

import pytest

from contract_sweeper.runtime.name_normalization import normalize_name


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Autopistas Metropolitanas de Puerto Rico LLC", "AUTOPISTAS METROPOLITANAS DE PUERTO RICO"),
        ("LGA Strategies, LLC", "LGA STRATEGIES"),
        ("Ferrovial Agroman, S.A.", "FERROVIAL AGROMAN"),
        ("LBG Consulting LLC", "LBG CONSULTING"),
        ("Brown & Sons Inc", "BROWN AND SONS"),
        ("  multiple   spaces  ", "MULTIPLE SPACES"),
    ],
)
def test_normalize_name_strips_legal_suffixes_and_canonicalizes(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.unit
def test_normalize_name_empty_inputs():
    assert normalize_name("") == ""
    assert normalize_name(None) == ""


@pytest.mark.unit
def test_normalize_name_only_suffix_returns_empty():
    assert normalize_name("LLC") == ""
    assert normalize_name("INC.") == ""


@pytest.mark.unit
def test_normalize_name_is_deterministic():
    assert normalize_name("Acme Corp") == normalize_name("ACME CORPORATION")
