"""Abstract base class for entity-mode on-demand adapters."""
from __future__ import annotations

import abc
from pathlib import Path

import pandas as pd

from ..entity_types import EntityQuery


class EntityAdapter(abc.ABC):
    """One concrete implementation per entity-mode source_id.

    Mirrors :class:`SourceAdapter` but consumes an :class:`EntityQuery`
    instead of a geographic :class:`Query`. Subclasses declare the
    identifier kinds they consume via :attr:`supported_kinds`; the
    dispatcher's caller-facing summary reports how many identifiers were
    skipped because no adapter consumed their kind.
    """

    #: Registry source_id this adapter serves.
    source_id: str = ""

    #: Identifier kinds this adapter can resolve. Identifiers whose kind
    #: is not in this set are silently skipped.
    supported_kinds: frozenset[str] = frozenset()

    def __init__(self, *, root: Path):
        self.root = Path(root)

    @abc.abstractmethod
    def fetch(self, query: EntityQuery) -> pd.DataFrame:
        """Fetch records for every supported identifier in ``query``.

        Raise :class:`CredentialMissing` if a required env var is unset.
        Other exceptions propagate to the dispatcher and become
        ``status='error'`` outcomes.
        """
