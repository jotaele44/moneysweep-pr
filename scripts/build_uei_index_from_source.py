"""
Build the vendor UEI index directly from source-provided UEIs in the master.

USASpending's ``spending_by_award`` API returns ``Recipient UEI`` on every award
record (see ``USASPENDING_FIELDS`` in ``scripts/auto_download.py``). Because the
PR contracts master is built from those same queries, the master already carries
each award's recipient UEI — so for the USASpending-sourced majority of rows we
can resolve vendor → UEI with **zero SAM.gov API calls** (no daily-quota wall,
no lossy name matching).

This produces the same ``vendor_uei_index.csv`` schema as ``sam_enrichment.py``
(reusing :func:`write_index`). SAM enrichment is then only needed to add the
fields USASpending does not carry (CAGE, registration status/expiry, parent
hierarchy) and to resolve the FPDS-native rows that lack a source UEI.

Output:
  data/staging/processed/enrichment/vendor_uei_index.csv

Usage:
  python3 scripts/build_uei_index_from_source.py
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.config import PROJECT_ROOT, setup_logging
from scripts.sam_enrichment import normalize_vendor, write_index

UEI_LEN = 12


def _find_col(columns: list[str], *needles: str) -> str | None:
    """First column whose lower-cased name contains all needles (in order-free)."""
    for col in columns:
        low = col.lower()
        if all(n in low for n in needles):
            return col
    return None


def build(root: Path | None = None) -> dict:
    root = Path(root or PROJECT_ROOT)
    logger = setup_logging("build_uei_index_from_source")

    master_path = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    output_dir = root / "data" / "staging" / "processed" / "enrichment"
    output_dir.mkdir(parents=True, exist_ok=True)

    if not master_path.exists():
        logger.error(f"Master not found: {master_path}")
        return {"status": "NO_MASTER", "rows": 0}

    df = pd.read_csv(master_path, dtype=str, low_memory=False).fillna("")
    cols = df.columns.tolist()

    vendor_col = _find_col(cols, "vendor", "name") or _find_col(cols, "recipient", "name")
    uei_col = _find_col(cols, "uei")
    amount_col = _find_col(cols, "obligated") or _find_col(cols, "amount")

    if not vendor_col or not uei_col:
        logger.error(f"Required columns missing — vendor={vendor_col!r} uei={uei_col!r}")
        return {"status": "NO_COLUMNS", "rows": 0}

    logger.info(f"[INIT] vendor={vendor_col!r} uei={uei_col!r} amount={amount_col!r}")

    # Per vendor: total value, and UEI vote weighted by obligated amount so the
    # UEI that actually received the most money wins ties.
    value_by_vendor: dict[str, float] = defaultdict(float)
    uei_weight: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for vendor, uei, amt in zip(
        df[vendor_col],
        df[uei_col],
        df[amount_col] if amount_col else [""] * len(df),
    ):
        vendor = (vendor or "").strip()
        if not vendor:
            continue
        try:
            value = float(amt) if amt not in ("", None) else 0.0
        except (ValueError, TypeError):
            value = 0.0
        value_by_vendor[vendor] += value
        uei = (uei or "").strip().upper()
        if len(uei) == UEI_LEN and uei.isalnum():
            uei_weight[vendor][uei] += max(value, 1.0)  # floor so zero-$ rows still vote

    results: dict[str, dict] = {}
    resolved = 0
    now = datetime.now().isoformat()
    for vendor, total_value in value_by_vendor.items():
        votes = uei_weight.get(vendor)
        best_uei = max(votes, key=lambda u: votes[u]) if votes else ""
        if best_uei:
            resolved += 1
        results[vendor] = {
            "vendor_name": vendor,
            "normalized_name": normalize_vendor(vendor),
            "total_value": total_value,
            "uei": best_uei,
            "cage": "",
            "duns": "",
            "sam_name": "",
            "match_score": 1.0 if best_uei else 0,
            "status": "SOURCE_UEI" if best_uei else "UNRESOLVED",
            "expiry": "",
            "state": "",
            "parent_uei": "",
            "parent_name": "",
            "source": "USASPENDING_SOURCE" if best_uei else "NONE",
            "resolved_at": now,
        }

    write_index(results, output_dir)

    total = len(results)
    value_total = sum(value_by_vendor.values())
    value_resolved = sum(value_by_vendor[v] for v, r in results.items() if r["uei"])
    logger.info("=" * 60)
    logger.info("[COMPLETE] vendor UEI index from source")
    logger.info(f"  Vendors:       {total:,}")
    logger.info(f"  UEI resolved:  {resolved:,} ({resolved / max(total, 1):.1%})")
    logger.info(
        f"  Value covered: ${value_resolved:,.0f} / ${value_total:,.0f} "
        f"({value_resolved / max(value_total, 1):.1%})"
    )
    logger.info(f"  → {output_dir / 'vendor_uei_index.csv'}")

    return {
        "status": "OK",
        "vendors": total,
        "resolved": resolved,
        "value_resolved": value_resolved,
        "value_total": value_total,
    }


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = build()
    print(
        f"\nSource UEI index: {result.get('resolved', 0):,}/{result.get('vendors', 0):,} vendors resolved"
    )
    sys.exit(0 if result.get("status") == "OK" else 1)
