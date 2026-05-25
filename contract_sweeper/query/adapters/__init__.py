"""Adapter registry for the on-demand query module.

Adds an entry per concrete adapter. Sources without a concrete adapter
are served by :class:`NotImplementedAdapter` via :func:`get_adapter`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Type

from .base import SourceAdapter
from ._stub import NotImplementedAdapter
from .fec import FECPRAdapter
from .openfema import OpenFEMAPaAdapter
from .usaspending import USAspendingPrimeAdapter

#: Concrete adapters keyed by their registry source_id.
ADAPTER_REGISTRY: dict[str, Type[SourceAdapter]] = {
    USAspendingPrimeAdapter.source_id: USAspendingPrimeAdapter,
    OpenFEMAPaAdapter.source_id: OpenFEMAPaAdapter,
    FECPRAdapter.source_id: FECPRAdapter,
}


def get_adapter(source_id: str, *, root: Path) -> SourceAdapter:
    """Return a concrete adapter for `source_id`, or the stub fallback."""
    cls = ADAPTER_REGISTRY.get(source_id)
    if cls is None:
        return NotImplementedAdapter(root=root, source_id=source_id)
    return cls(root=root)


__all__ = ["ADAPTER_REGISTRY", "get_adapter", "SourceAdapter", "NotImplementedAdapter"]
