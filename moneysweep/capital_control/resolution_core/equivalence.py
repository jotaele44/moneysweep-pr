from __future__ import annotations

from dataclasses import dataclass
from typing import AbstractSet, Hashable


@dataclass(frozen=True)
class EquivalenceSets:
    intersection: frozenset[Hashable]
    a_only: frozenset[Hashable]
    b_only: frozenset[Hashable]
    union: frozenset[Hashable]
    symmetric_difference: frozenset[Hashable]


def compute_equivalence_sets(a: AbstractSet[Hashable], b: AbstractSet[Hashable]) -> EquivalenceSets:
    left = frozenset(a)
    right = frozenset(b)
    return EquivalenceSets(
        intersection=left & right,
        a_only=left - right,
        b_only=right - left,
        union=left | right,
        symmetric_difference=left ^ right,
    )
