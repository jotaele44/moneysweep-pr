from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class ChangeState(str, Enum):
    UNCHANGED = "UNCHANGED"
    CHANGED = "CHANGED"
    NEW_PRIMARY_ARTIFACT = "NEW_PRIMARY_ARTIFACT"
    NEW_STABLE_ID = "NEW_STABLE_ID"
    SOURCE_RECOVERED = "SOURCE_RECOVERED"
    SOURCE_BECAME_INACCESSIBLE = "SOURCE_BECAME_INACCESSIBLE"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class BaselineDiff:
    state: ChangeState
    changed_keys: tuple[str, ...]


def diff_baseline(baseline: Mapping[str, object], current: Mapping[str, object]) -> BaselineDiff:
    keys = set(baseline) | set(current)
    changed = tuple(sorted(key for key in keys if baseline.get(key) != current.get(key)))
    return BaselineDiff(ChangeState.CHANGED if changed else ChangeState.UNCHANGED, changed)
