"""Fail-closed adapter for the Dateas Puerto Rico metadata catalog."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..types import ManualOnlyError, Query
from .base import SourceAdapter


REGISTRY_RELATIVE_PATH = Path("registries/source_registry_extensions/dateas_pr_metadata_v0_1.yaml")


class DateasPRMetadataOnlyAdapter(SourceAdapter):
    """Expose the static registry path while rejecting query execution."""

    source_id = "dateas_pr_discovery"
    metadata_only = True
    row_ingestion_enabled = False
    canonical_promotion_enabled = False
    scheduled_polling_enabled = False

    @property
    def registry_path(self) -> Path:
        return self.root / REGISTRY_RELATIVE_PATH

    def fetch(self, query: Query) -> pd.DataFrame:
        raise ManualOnlyError(
            source_id=self.source_id,
            producer_script=str(REGISTRY_RELATIVE_PATH),
            authentication="disabled_metadata_only",
        )
