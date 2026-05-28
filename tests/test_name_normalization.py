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


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Municipio de San Juan", "MUNICIPIO SAN JUAN"),
        ("MUNICIPALITY OF SAN JUAN", "MUNICIPIO SAN JUAN"),
        ("Municipio Autónomo de San Juan", "MUNICIPIO SAN JUAN"),
        ("Municipio Autonomo de Ponce", "MUNICIPIO PONCE"),
        ("MUNICIPIO DE CAMUY", "MUNICIPIO CAMUY"),
        ("Municipality of the Capital", "MUNICIPIO CAPITAL"),
    ],
)
def test_normalize_name_bridges_bilingual_municipio_prefix(raw, expected):
    """Spanish and English municipio designators collapse to one canonical."""
    assert normalize_name(raw) == expected


@pytest.mark.unit
def test_normalize_name_municipio_bilingual_pairs_collapse():
    """The Spanish and English forms of the same municipio must be equal."""
    assert normalize_name("Municipio de San Juan") == normalize_name("Municipality of San Juan")
    assert normalize_name("Municipio Autónomo de Ponce") == normalize_name("Municipality of Ponce")


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        # "de Puerto Rico" mid-string is not a municipio prefix.
        ("Autopistas Metropolitanas de Puerto Rico LLC", "AUTOPISTAS METROPOLITANAS DE PUERTO RICO"),
        # "Deportivo" starts with "De" but is not the standalone "de" connector.
        ("Municipio Deportivo XYZ", "MUNICIPIO DEPORTIVO XYZ"),
        # "Municipal" is not "Municipio"/"Municipality of".
        ("Municipal Bonds Inc", "MUNICIPAL BONDS"),
    ],
)
def test_normalize_name_municipio_rule_no_false_positives(raw, expected):
    assert normalize_name(raw) == expected
