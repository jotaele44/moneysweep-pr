"""Source-maturity → claim-tier translation.

Reads ``reports/source_registry_status.csv`` (produced by
``scripts/gap_analysis_builder.py``) and provides a consistent way for
downstream report writers and graph builders to label their claims per
``docs/CLAIM_LANGUAGE_POLICY.md``.

Vocabulary alignment:

  pipeline_status                 → claim_tier
  ─────────────────────────────────────────────
  fully_materialized              → observed
  partially_materialized          → linked
  not_materialized                → blocked
  below_threshold                 → blocked
  no_outputs_declared             → observed (nothing to materialize)
  <missing from CSV / unknown>    → blocked

When a claim depends on multiple datasets, the *worst* tier wins:
``blocked`` > ``linked`` > ``observed``.
"""
from __future__ import annotations

import csv
from pathlib import Path

# Tier ranking — higher value means more restrictive.
TIER_RANK = {"observed": 0, "linked": 1, "blocked": 2}
RANK_TIER = {v: k for k, v in TIER_RANK.items()}

_STATUS_TO_TIER = {
    "fully_materialized": "observed",
    "partially_materialized": "linked",
    "not_materialized": "blocked",
    "below_threshold": "blocked",
    "no_outputs_declared": "observed",
}

DEFAULT_STATUS_CSV = "reports/source_registry_status.csv"


def load_source_maturity(root: Path, status_csv: str = DEFAULT_STATUS_CSV) -> dict[str, str]:
    """Return ``{source_id: pipeline_status}`` for every row in the status CSV.

    Returns an empty dict if the CSV is absent (no maturity gating applied).
    """
    path = Path(root) / status_csv
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            src = (row.get("source_id") or "").strip()
            status = (row.get("pipeline_status") or "").strip()
            if src and status:
                out[src] = status
    return out


def load_dataset_to_source_map(
    root: Path, status_csv: str = DEFAULT_STATUS_CSV
) -> dict[str, str]:
    """Return ``{output_filename: source_id}`` derived from expected_outputs.

    The status CSV stores expected_outputs as a semicolon-separated list of
    repo-relative paths. This indexes the leaf filename so callers that only
    know the dataset file (e.g. ``pr_emma_bonds.csv``) can resolve the
    owning source.
    """
    path = Path(root) / status_csv
    if not path.exists():
        return {}
    out: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            src = (row.get("source_id") or "").strip()
            outputs = (row.get("expected_outputs") or "").strip()
            if not src or not outputs:
                continue
            for entry in outputs.split(";"):
                leaf = Path(entry.strip()).name
                if leaf:
                    out.setdefault(leaf, src)
    return out


def claim_tier(
    source_datasets: list[str],
    maturity: dict[str, str],
    dataset_map: dict[str, str],
) -> str:
    """Return the worst claim tier across the given source datasets.

    ``source_datasets`` may contain either dataset filenames
    (``pr_emma_bonds.csv``) or source_ids (``emma_bonds``). Unknown
    datasets are treated as ``blocked`` (precautionary).
    """
    if not source_datasets:
        return "blocked"
    worst_rank = TIER_RANK["observed"]
    saw_any = False
    for ds in source_datasets:
        if not ds:
            continue
        saw_any = True
        leaf = Path(ds).name
        source_id = dataset_map.get(leaf) or (
            ds if ds in maturity else None
        )
        if source_id is None:
            tier = "blocked"
        else:
            status = maturity.get(source_id, "")
            tier = _STATUS_TO_TIER.get(status, "blocked")
        if TIER_RANK[tier] > worst_rank:
            worst_rank = TIER_RANK[tier]
    if not saw_any:
        return "blocked"
    return RANK_TIER[worst_rank]


def unmaterialized_sources(
    source_datasets: list[str],
    maturity: dict[str, str],
    dataset_map: dict[str, str],
) -> list[str]:
    """Return the subset of ``source_datasets`` whose tier is ``blocked``."""
    out: list[str] = []
    for ds in source_datasets:
        if not ds:
            continue
        if claim_tier([ds], maturity, dataset_map) == "blocked":
            out.append(ds)
    return out
