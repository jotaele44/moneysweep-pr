from __future__ import annotations

from collections import Counter
from typing import Hashable, Iterable

from .models import Cardinality


def classify_join_cardinality(
    left_keys: Iterable[Hashable], right_keys: Iterable[Hashable]
) -> Cardinality:
    left = Counter(left_keys)
    right = Counter(right_keys)
    common = set(left) & set(right)
    if not common:
        return Cardinality.ZERO_TO_ONE
    left_many = any(left[key] > 1 for key in common)
    right_many = any(right[key] > 1 for key in common)
    if left_many and right_many:
        return Cardinality.MANY_TO_MANY
    if left_many:
        return Cardinality.MANY_TO_ONE
    if right_many:
        return Cardinality.ONE_TO_MANY
    return Cardinality.ONE_TO_ONE


def assert_no_unsafe_many_to_many(
    left_keys: Iterable[Hashable], right_keys: Iterable[Hashable]
) -> Cardinality:
    cardinality = classify_join_cardinality(left_keys, right_keys)
    if cardinality is Cardinality.MANY_TO_MANY:
        raise ValueError("unsafe many-to-many join would multiply records")
    return cardinality
