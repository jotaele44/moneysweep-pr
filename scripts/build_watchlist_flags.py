"""Generate the queryable flag manifest for the ``epstein_pr_case`` watchlist.

Reads the quarantined wire records under ``data/watchlists/epstein_pr_case/`` and
writes ``registries/watchlists/epstein_pr_case.json`` — the flagged entities,
banks, and transactions used to cross-reference incoming public-money data.

These records are NOT a public-money source and are never materialized (see the
watchlist README). This builder only distills them into a reviewable flag list.
Deterministic / byte-identical on re-run; no network.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.watchlist import normalize_entity

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = REPO_ROOT / "data" / "watchlists" / "epstein_pr_case"
OUT = REPO_ROOT / "registries" / "watchlists" / "epstein_pr_case.json"


def _read(name: str) -> list[dict]:
    path = RAW_DIR / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def build() -> dict:
    ledger = _read("EP_PR_PRBank_Wire_Ledger_ALL.csv")
    by_entity = _read("EP_PR_PRBank_Summary_ByEntity.csv")

    entities = sorted({normalize_entity(r.get("entity_clean", "")) for r in by_entity} - {""})
    banks = sorted({(r.get("destination_bank") or "").strip() for r in (ledger + by_entity)} - {""})
    transactions = sorted(
        (
            {
                "txn_date": (r.get("txn_date") or "").strip(),
                "entity": normalize_entity(r.get("entity_raw", "")),
                "destination_bank": (r.get("destination_bank") or "").strip(),
                "amount_usd": (r.get("amount_usd") or "").strip(),
            }
            for r in ledger
        ),
        key=lambda t: (t["txn_date"], t["entity"], t["amount_usd"], t["destination_bank"]),
    )

    return {
        "schema_version": "watchlist_v1",
        "watchlist_id": "epstein_pr_case",
        "status": "flagged_reference_only",
        "do_not_materialize": True,
        "purpose": (
            "Cross-reference flag only — NOT a public-money source. Flag overlaps with "
            "incoming public-money data (contracts, grants, donations, wires) for human review."
        ),
        "source_case": "EP_PR_CASE",
        "flagged_entities": entities,
        "flagged_banks": banks,
        "transaction_count": len(transactions),
        "transactions": transactions,
        "generated_from": [
            "data/watchlists/epstein_pr_case/EP_PR_PRBank_Wire_Ledger_ALL.csv",
            "data/watchlists/epstein_pr_case/EP_PR_PRBank_Summary_ByEntity.csv",
        ],
    }


def main() -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    manifest = build()
    OUT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT.relative_to(REPO_ROOT)} "
        f"({len(manifest['flagged_entities'])} entities, {manifest['transaction_count']} txns)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
