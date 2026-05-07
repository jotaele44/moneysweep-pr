"""Canonical normalization layer for Phase 3."""

from .canonical_contracts import CANONICAL_CONTRACT_FIELDS
from .normalization_runner import NormalizationRunSummary, run_normalization
from .source_normalizer import SourceContractsNormalizer

__all__ = [
    "CANONICAL_CONTRACT_FIELDS",
    "NormalizationRunSummary",
    "SourceContractsNormalizer",
    "run_normalization",
]
