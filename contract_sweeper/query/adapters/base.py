"""Abstract base class for on-demand source adapters."""

from __future__ import annotations

import abc
from pathlib import Path

import pandas as pd

from ..types import Query


class SourceAdapter(abc.ABC):
    """One concrete implementation per source_id.

    Adapters fetch a query-shaped slice of a single upstream source. They
    return a raw DataFrame in the source's native column shape; the
    dispatcher is responsible for running `apply_post_ingest()` to attach
    canonical geo columns. Adapters MUST NOT write to disk — the
    dispatcher's cache layer handles persistence.
    """

    #: Registry source_id this adapter serves.
    source_id: str = ""

    def __init__(self, *, root: Path):
        self.root = Path(root)

    @abc.abstractmethod
    def fetch(self, query: Query) -> pd.DataFrame:
        """Fetch the slice of this source matching the query.

        Raise :class:`ManualOnlyError` if no on-demand path exists.
        Raise :class:`CredentialMissing` if a required env var is unset.
        Other exceptions propagate to the dispatcher and become
        `status='error'` outcomes.
        """
