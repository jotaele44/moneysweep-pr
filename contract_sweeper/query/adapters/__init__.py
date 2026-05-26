"""Adapter registry for the on-demand query module.

Adds an entry per concrete adapter. Sources without a concrete adapter
are served by :class:`NotImplementedAdapter` via :func:`get_adapter`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Type

from .base import SourceAdapter
from ._stub import NotImplementedAdapter
from .fdic import FDICInstitutionsAdapter
from .fec import FECPRAdapter
from .highergov import HigherGovSupplementalAdapter
from .lda import LDAAdapter
from .nih import NIHReporterAdapter
from .nonprofits import NonprofitsIRS990Adapter
from .nsf import NSFAwardsAdapter
from .opencorporates import OpenCorporatesAdapter
from .openfema import (
    OpenFEMAHmgpAdapter,
    OpenFEMANfipClaimsAdapter,
    OpenFEMAPaAdapter,
)
from .sba import SBALoansAdapter, SBAPaycheckProtectionAdapter
from .sbir import SBIRAdapter
from .usaspending import (
    DOEGrantsAdapter,
    DOJGrantsAdapter,
    DOTGrantsAdapter,
    EDGrantsAdapter,
    EPAGrantsAdapter,
    EXIMBankAdapter,
    HAFAdapter,
    HHSGrantsAdapter,
    OIAGrantsAdapter,
    SLFRFAdapter,
    USAspendingGrantsAdapter,
    USAspendingPrimeAdapter,
    USAspendingSubawardsAdapter,
    USDAGrantsAdapter,
)

#: Concrete adapters keyed by their registry source_id.
ADAPTER_REGISTRY: dict[str, Type[SourceAdapter]] = {
    USAspendingPrimeAdapter.source_id: USAspendingPrimeAdapter,
    USAspendingSubawardsAdapter.source_id: USAspendingSubawardsAdapter,
    USAspendingGrantsAdapter.source_id: USAspendingGrantsAdapter,
    OpenFEMAPaAdapter.source_id: OpenFEMAPaAdapter,
    OpenFEMAHmgpAdapter.source_id: OpenFEMAHmgpAdapter,
    FECPRAdapter.source_id: FECPRAdapter,
    NIHReporterAdapter.source_id: NIHReporterAdapter,
    SBIRAdapter.source_id: SBIRAdapter,
    # Per-agency USAspending grant adapters
    EPAGrantsAdapter.source_id: EPAGrantsAdapter,
    DOTGrantsAdapter.source_id: DOTGrantsAdapter,
    EDGrantsAdapter.source_id: EDGrantsAdapter,
    HHSGrantsAdapter.source_id: HHSGrantsAdapter,
    DOEGrantsAdapter.source_id: DOEGrantsAdapter,
    DOJGrantsAdapter.source_id: DOJGrantsAdapter,
    USDAGrantsAdapter.source_id: USDAGrantsAdapter,
    OIAGrantsAdapter.source_id: OIAGrantsAdapter,
    # Distinct-API adapters
    LDAAdapter.source_id: LDAAdapter,
    NSFAwardsAdapter.source_id: NSFAwardsAdapter,
    # OpenFEMA NFIP claims (same v2 surface as fema_pa)
    OpenFEMANfipClaimsAdapter.source_id: OpenFEMANfipClaimsAdapter,
    # USAspending program-narrows (Treasury / EXIM)
    SLFRFAdapter.source_id: SLFRFAdapter,
    HAFAdapter.source_id: HAFAdapter,
    EXIMBankAdapter.source_id: EXIMBankAdapter,
    # New distinct-API adapters
    FDICInstitutionsAdapter.source_id: FDICInstitutionsAdapter,
    NonprofitsIRS990Adapter.source_id: NonprofitsIRS990Adapter,
    SBALoansAdapter.source_id: SBALoansAdapter,
    SBAPaycheckProtectionAdapter.source_id: SBAPaycheckProtectionAdapter,
    # Auth-gated adapters (Batch 6)
    OpenCorporatesAdapter.source_id: OpenCorporatesAdapter,
    HigherGovSupplementalAdapter.source_id: HigherGovSupplementalAdapter,
}


def get_adapter(source_id: str, *, root: Path) -> SourceAdapter:
    """Return a concrete adapter for `source_id`, or the stub fallback."""
    cls = ADAPTER_REGISTRY.get(source_id)
    if cls is None:
        return NotImplementedAdapter(root=root, source_id=source_id)
    return cls(root=root)


__all__ = ["ADAPTER_REGISTRY", "get_adapter", "SourceAdapter", "NotImplementedAdapter"]
