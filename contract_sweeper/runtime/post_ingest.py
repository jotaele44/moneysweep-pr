"""Shared post-ingest enrichment for every source in the registry.

Every producer (a `scripts/download_*.py` / `scripts/ingest_*.py` /
`scripts/build_*.py`) should call `apply_post_ingest()` on its dataframe
immediately before writing the registry-declared `expected_outputs`. The
backfill script (`scripts/backfill_geo_attribution.py`) applies the same
function to files already on disk, and the on-demand query dispatcher applies it
to adapter results.

Enrichment steps (all additive and idempotent — they only add canonical columns,
never overwrite source columns, and re-running is a no-op):

    1. Geographic attribution   — PR municipality FIPS on a canonical schema.
    2. Entity normalization     — ``entity_normalized`` clustering key from the
       row's entity-name column.
    3. Currency canonicalization — ``<amount>_canonical`` numeric columns parsed
       from formatted money strings.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from contract_sweeper.runtime.geo_attribution import attribute_geo
from contract_sweeper.runtime.name_normalization import normalize_name

# Candidate entity-name columns across the source families, in priority order.
ENTITY_NAME_COLUMNS = (
    "recipient_name",
    "vendor_name",
    "awardee_or_recipient_legal",
    "legal_entity_name",
    "prime_recipient_name",
    "subawardee_name",
    "contributor_name",
    "registrant_name",
    "client_name",
    "lobbyist_name",
    "applicant_name",
    "issuer_name",
    "issuer",
    "organization_name",
    "legal_name",
)

# Money columns that should gain a parsed numeric ``<col>_canonical`` companion.
AMOUNT_COLUMNS = (
    "obligated_amount",
    "amount",
    "federal_action_obligation",
    "total_obligation",
    "obligation_amount",
    "subaward_amount",
    "federal_share_obligated",
    "project_amount",
    "contribution_receipt_amount",
    "eligible_amount",
    "federal_share",
    "income",
    "expenses",
    "total_approved",
)

_CURRENCY_STRIP = re.compile(r"[^0-9.\-]")


def _to_number(value) -> float | None:
    """Parse a formatted money string (``$1,234.50``, ``(500)``) to a float."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip()
    if not text:
        return None
    negative = text.startswith("(") and text.endswith(")")
    cleaned = _CURRENCY_STRIP.sub("", text)
    if cleaned in ("", "-", ".", "-."):
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    return -number if negative else number


def normalize_entities(df: pd.DataFrame) -> pd.DataFrame:
    """Add an ``entity_normalized`` clustering key from the first entity column.

    Idempotent: skips when the column already exists or no entity column is found.
    """
    if "entity_normalized" in df.columns:
        return df
    for col in ENTITY_NAME_COLUMNS:
        if col in df.columns:
            df = df.copy()
            df["entity_normalized"] = df[col].fillna("").astype(str).map(normalize_name)
            return df
    return df


def canonicalize_currency(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``<col>_canonical`` numeric companions for recognized money columns.

    Non-destructive: source columns are left untouched. Idempotent: a canonical
    column that already exists is not recomputed.
    """
    additions: dict[str, object] = {}
    for col in AMOUNT_COLUMNS:
        canonical = f"{col}_canonical"
        if col in df.columns and canonical not in df.columns:
            additions[canonical] = df[col].map(_to_number)
    if additions:
        df = df.copy()
        for name, series in additions.items():
            df[name] = series
    return df


def apply_post_ingest(
    df: pd.DataFrame,
    *,
    source_id: str,
    root: Path | None = None,
) -> pd.DataFrame:
    """Run every post-ingest enrichment step on `df`.

    Steps: geo attribution, entity normalization, currency canonicalization.
    All steps are additive and idempotent, so re-running on an already-enriched
    dataframe is a no-op.
    """
    df = attribute_geo(df, source_id=source_id, root=root)
    if df is None or len(df) == 0:
        return df
    df = normalize_entities(df)
    df = canonicalize_currency(df)
    return df
