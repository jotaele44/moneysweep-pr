"""Tests for the entity-mode Query types."""

from __future__ import annotations

import pytest

from contract_sweeper.query.entity_types import (
    SUPPORTED_KINDS,
    EntityIdentifier,
    EntityQuery,
)


@pytest.mark.unit
def test_entity_identifier_validates_kind():
    with pytest.raises(ValueError):
        EntityIdentifier(kind="invalid", value="x")  # type: ignore[arg-type]


@pytest.mark.unit
def test_entity_identifier_rejects_empty_value():
    with pytest.raises(ValueError):
        EntityIdentifier(kind="uei", value="")
    with pytest.raises(ValueError):
        EntityIdentifier(kind="uei", value="   ")


@pytest.mark.unit
def test_supported_kinds_matches_literal():
    expected = {"uei", "name", "cage", "duns", "ein", "cik"}
    assert SUPPORTED_KINDS == expected


@pytest.mark.unit
def test_entity_query_canonical_dict_sorts_and_dedups():
    eq = EntityQuery(
        identifiers=(
            EntityIdentifier(kind="name", value="Zeta"),
            EntityIdentifier(kind="uei", value="ABC123"),
            EntityIdentifier(kind="name", value="Alpha"),
            EntityIdentifier(kind="name", value="Alpha"),  # duplicate
        )
    )
    out = eq.canonical_dict()["identifiers"]
    assert out == [
        {"kind": "name", "value": "Alpha"},
        {"kind": "name", "value": "Zeta"},
        {"kind": "uei", "value": "ABC123"},
    ]


@pytest.mark.unit
def test_entity_query_hash_is_order_insensitive():
    a = EntityQuery(
        identifiers=(
            EntityIdentifier(kind="uei", value="A"),
            EntityIdentifier(kind="name", value="X"),
        )
    )
    b = EntityQuery(
        identifiers=(
            EntityIdentifier(kind="name", value="X"),
            EntityIdentifier(kind="uei", value="A"),
        )
    )
    assert a.canonical_hash() == b.canonical_hash()


@pytest.mark.unit
def test_entity_query_hash_changes_with_different_identifiers():
    a = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="A"),))
    b = EntityQuery(identifiers=(EntityIdentifier(kind="uei", value="B"),))
    assert a.canonical_hash() != b.canonical_hash()


@pytest.mark.unit
def test_entity_query_by_kind_filters_and_dedups():
    eq = EntityQuery(
        identifiers=(
            EntityIdentifier(kind="uei", value="A"),
            EntityIdentifier(kind="uei", value="B"),
            EntityIdentifier(kind="name", value="X"),
            EntityIdentifier(kind="uei", value="A"),  # dup
        )
    )
    assert eq.by_kind("uei") == ["A", "B"]
    assert eq.by_kind("name") == ["X"]
    assert eq.by_kind("cage") == []
    assert eq.by_kind("uei", "name") == ["A", "B", "X"]


@pytest.mark.unit
def test_empty_entity_query_has_stable_hash():
    a = EntityQuery()
    b = EntityQuery()
    assert a.canonical_hash() == b.canonical_hash()
    assert a.canonical_dict() == {"identifiers": []}
