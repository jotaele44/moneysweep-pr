"""Fallback adapter for the 79 sources without on-demand implementations."""
from __future__ import annotations

import pandas as pd

from contract_sweeper.runtime.source_registry import source_by_id

from ..types import ManualOnlyError, Query
from .base import SourceAdapter


class NotImplementedAdapter(SourceAdapter):
    """Returned by the registry for any source_id lacking a concrete adapter.

    Raises :class:`ManualOnlyError` on `fetch()` with a structured payload
    pointing at the registry's `producer_script` so the caller knows how
    the bulk path would otherwise produce this source.
    """

    def __init__(self, *, root, source_id: str):
        super().__init__(root=root)
        self.source_id = source_id

    def fetch(self, query: Query) -> pd.DataFrame:
        src = source_by_id(self.source_id, self.root) or {}
        raise ManualOnlyError(
            source_id=self.source_id,
            producer_script=src.get("producer_script"),
            authentication=src.get("authentication"),
        )
