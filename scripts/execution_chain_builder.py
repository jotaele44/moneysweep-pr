"""Build execution chains linking prime awards → subawards → assets → municipalities.

Reads:
  data/staging/processed/pr_subawards_master.csv
  data/staging/processed/pr_prime_sub_relationships.csv  (optional summary)
  data/staging/processed/pr_all_awards_master.csv
  data/staging/processed/pr_contracts_master.csv
  data/staging/processed/entities_resolved.csv            (parent_uei enrichment)

Writes:
  data/staging/processed/execution/execution_chain_master.csv
  data/staging/processed/execution/execution_chain_per_asset.csv
  data/staging/processed/execution/execution_chain_per_municipality.csv
  data/staging/processed/execution/execution_chain_review_queue.csv

Usage:
  python3 scripts/execution_chain_builder.py
  python3 scripts/execution_chain_builder.py --root /path/to/repo
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

NAME_FIELDS = ["recipient_name", "vendor_name", "prime_recipient_name", "prime_name"]
UEI_FIELDS = ["recipient_uei", "uei", "prime_uei", "prime_recipient_uei"]
PARENT_UEI_FIELDS = ["parent_uei", "prime_parent_uei", "ultimate_parent_uei"]
AMOUNT_FIELDS = ["obligated_amount", "total_obligation", "obligation_amount", "amount"]
AWARD_ID_FIELDS = [
    "award_id",
    "prime_award_id",
    "prime_award_ids",
    "prime_award_generated_internal_id",
    "generated_internal_id",
    "contract_id",
    "generated_unique_award_id",
    "prime_award_unique_key",
]
# Fields a subaward row may carry that identify its prime award, in join-priority
# order: the USAspending generated internal id is the strongest (matches the prime
# contracts master's generated_internal_id exactly); plural variants come from the
# pre-aggregated pr_prime_sub_relationships.csv summary.
SUB_JOIN_FIELDS = [
    "prime_award_generated_internal_id",
    "prime_award_id",
    "prime_award_ids",
    "award_id",
    "generated_unique_award_id",
    "prime_award_unique_key",
]
# Keys to index the prime-award masters by, so any of the above resolves.
PRIME_KEY_FIELDS = [
    "generated_internal_id",
    "contract_id",
    "award_id",
    "generated_unique_award_id",
    "prime_award_unique_key",
]
PRIME_NAME_FIELDS = ["prime_recipient_name", "prime_name", "prime_recipient"]
FUNDING_FIELDS = [
    "funding_source",
    "funding_agency",
    "awarding_agency",
    "awarding_agencies",
    "awarding_sub_agency",
]
SUBAWARD_ID_FIELDS = ["subaward_id", "subaward_number", "generated_unique_subaward_id"]
MUNICIPALITY_FIELDS = [
    "municipality",
    "pop_county",
    "county",
    "pop_city",
    "place_of_performance_city",
]


def _read_csv(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0 or path.suffix.lower() != ".csv":
        return []
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _first(row: dict, fields: list[str]) -> str:
    for f in fields:
        v = row.get(f)
        if v not in (None, ""):
            return str(v).strip()
    return ""


def _money(row: dict) -> float:
    for f in AMOUNT_FIELDS:
        v = row.get(f)
        if v not in (None, ""):
            try:
                return float(str(v).replace(",", "").replace("$", ""))
            except Exception:
                pass
    return 0.0


def _chain_id(*parts: str) -> str:
    return hashlib.sha1("|".join(p or "" for p in parts).encode()).hexdigest()[:16]


def _load_prime_index(root: Path) -> dict[str, dict]:
    """Index prime awards by every identifier a subaward might join on.

    A subaward's prime is identified by USAspending's generated internal id
    (e.g. CONT_AWD_W912DY18F0003_9700_...), which matches pr_contracts_master's
    ``generated_internal_id``. Older masters key on ``award_id``. We index every
    candidate key so any of them resolves.
    """
    idx: dict[str, dict] = {}
    for path in [
        root / "data/staging/processed/pr_all_awards_master.csv",
        root / "data/staging/processed/pr_contracts_master.csv",
        root / "data/staging/processed/pr_fema_pa_master.csv",
    ]:
        for row in _read_csv(path):
            for kf in PRIME_KEY_FIELDS:
                k = (row.get(kf) or "").strip()
                if k:
                    idx.setdefault(k, row)
    return idx


def _load_entity_index(root: Path) -> dict[str, dict]:
    """UEI → entity row with parent_uei from entities_resolved.csv."""
    idx: dict[str, dict] = {}
    for row in _read_csv(root / "data/staging/processed/entities_resolved.csv"):
        uei = row.get("entity_uei", "").strip()
        if uei:
            idx[uei] = row
    return idx


def _link_confidence(
    aid: str,
    prime: str,
    subn: str,
    prime_uei: str,
    sub_uei: str,
    prime_in_index: bool,
    strong_key: bool,
) -> float:
    """Confidence that a subaward is correctly linked to its prime award.

    ``strong_key`` means the subaward carries USAspending's authoritative prime
    generated-internal-id — a source-published linkage, the strongest signal.
    ``prime_in_index`` means we also hold that prime locally (enrichable).
    """
    score = 0.0
    score += 0.40 if strong_key else (0.25 if aid else 0.0)
    score += 0.20 if prime else 0.0
    score += 0.15 if prime_in_index else 0.0
    score += 0.15 if subn else 0.0
    score += 0.05 if prime_uei else 0.0
    score += 0.05 if sub_uei else 0.0
    return round(min(score, 1.0), 3)


def build_execution_chains(root: Path) -> dict[str, Any]:
    proc = root / "data/staging/processed"
    prime_idx = _load_prime_index(root)
    entity_idx = _load_entity_index(root)

    sub_rows: list[dict] = []
    for path in [proc / "pr_subawards_master.csv", proc / "pr_prime_sub_relationships.csv"]:
        sub_rows.extend(_read_csv(path))

    chains: list[dict] = []
    review: list[dict] = []

    for i, s in enumerate(sub_rows, 1):
        aid = _first(s, SUB_JOIN_FIELDS)
        m = prime_idx.get(aid, {})
        strong_key = bool((s.get("prime_award_generated_internal_id") or "").strip())

        prime = _first(s, PRIME_NAME_FIELDS) or _first(m, NAME_FIELDS)
        subn = _first(
            s,
            [
                "sub_recipient_name",
                "subawardee_name",
                "sub_name",
                "sub_recipient",
                "recipient_name",
            ],
        )

        prime_uei = _first(s, ["prime_uei", "prime_recipient_uei"]) or _first(m, UEI_FIELDS)
        sub_uei = _first(s, ["sub_uei", "sub_recipient_uei", "subawardee_uei", "recipient_uei"])

        # Enrich parent_uei from entities_resolved
        prime_parent_uei = _first(s, ["prime_parent_uei"]) or _first(m, PARENT_UEI_FIELDS)
        if not prime_parent_uei and prime_uei and prime_uei in entity_idx:
            prime_parent_uei = entity_idx[prime_uei].get("parent_uei", "")
        sub_parent_uei = _first(s, ["sub_parent_uei"])
        if not sub_parent_uei and sub_uei and sub_uei in entity_idx:
            sub_parent_uei = entity_idx[sub_uei].get("parent_uei", "")

        municipality = _first(s, MUNICIPALITY_FIELDS) or _first(m, MUNICIPALITY_FIELDS)
        asset_id = _first(s, ["asset_id", "facility_id", "project_number", "project_id"]) or _first(
            m, ["asset_id", "facility_id", "project_number", "project_id"]
        )

        conf = _link_confidence(aid, prime, subn, prime_uei, sub_uei, bool(m), strong_key)

        if aid and m:
            link_method = "prime_award_id_join"
        elif aid and prime:
            # USAspending publishes the prime↔sub relationship in the subaward
            # record itself; the prime award is identified even when it is not
            # also present in our locally-downloaded prime masters.
            link_method = "subaward_declared_prime"
        else:
            link_method = "subaward_record_only"

        chain: dict = {
            "chain_id": _chain_id(aid, prime, subn, str(i)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "funding_source": _first(m, FUNDING_FIELDS) or _first(s, FUNDING_FIELDS),
            "program": _first(m, ["program", "assistance_listing", "cfda_number", "award_category"])
            or _first(s, ["award_category"]),
            "prime_name": prime,
            "prime_uei": prime_uei,
            "prime_parent_uei": prime_parent_uei,
            "sub_name": subn,
            "sub_uei": sub_uei,
            "sub_parent_uei": sub_parent_uei,
            "award_id": aid,
            "subaward_id": _first(s, SUBAWARD_ID_FIELDS),
            "project_id": _first(s, ["project_id", "project_number"])
            or _first(m, ["project_id", "project_number"]),
            "asset_id": asset_id,
            "municipality": municipality,
            "obligation_amount": _money(m),
            "subaward_amount": _money(s),
            "link_method": link_method,
            "link_confidence": conf,
            "manual_review_required": conf < 0.9,
        }
        chains.append(chain)
        if chain["manual_review_required"]:
            review.append(chain)

    # Per-asset aggregation
    by_asset: dict[str, dict] = {}
    for c in chains:
        key = c["asset_id"] or c["project_id"] or ""
        if not key:
            continue
        if key not in by_asset:
            by_asset[key] = {
                "asset_id": key,
                "prime_name": c["prime_name"],
                "prime_uei": c["prime_uei"],
                "prime_parent_uei": c["prime_parent_uei"],
                "municipality": c["municipality"],
                "chain_count": 0,
                "total_obligation": 0.0,
                "total_subaward": 0.0,
            }
        by_asset[key]["chain_count"] += 1
        by_asset[key]["total_obligation"] += c["obligation_amount"]
        by_asset[key]["total_subaward"] += c["subaward_amount"]

    # Per-municipality aggregation
    by_muni: dict[str, dict] = {}
    for c in chains:
        muni = c["municipality"] or "UNKNOWN"
        if muni not in by_muni:
            by_muni[muni] = {
                "municipality": muni,
                "chain_count": 0,
                "unique_primes": set(),
                "unique_subs": set(),
                "total_obligation": 0.0,
                "total_subaward": 0.0,
            }
        by_muni[muni]["chain_count"] += 1
        by_muni[muni]["unique_primes"].add(c["prime_name"] or "")
        by_muni[muni]["unique_subs"].add(c["sub_name"] or "")
        by_muni[muni]["total_obligation"] += c["obligation_amount"]
        by_muni[muni]["total_subaward"] += c["subaward_amount"]

    muni_rows = [
        {
            **{k: v for k, v in r.items() if k not in ("unique_primes", "unique_subs")},
            "unique_prime_count": len(r["unique_primes"]),
            "unique_sub_count": len(r["unique_subs"]),
        }
        for r in by_muni.values()
    ]
    muni_rows.sort(key=lambda r: -r["total_obligation"])

    out = proc / "execution"
    _write_csv(out / "execution_chain_master.csv", chains)
    _write_csv(out / "execution_chain_per_asset.csv", list(by_asset.values()))
    _write_csv(out / "execution_chain_per_municipality.csv", muni_rows)
    _write_csv(out / "execution_chain_review_queue.csv", review)

    # A chain is "linked" when the prime award is identified (either matched into
    # our prime index, or declared authoritatively in the subaward record itself).
    # "enriched" is the stricter subset whose prime we also hold locally.
    enriched = sum(1 for c in chains if c["link_method"] == "prime_award_id_join")
    declared = sum(1 for c in chains if c["link_method"] == "subaward_declared_prime")
    linked = enriched + declared
    linkage_rate = linked / len(chains) if chains else 0.0
    full_chains = sum(1 for c in chains if c["prime_name"] and c["sub_name"] and c["award_id"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chain_count": len(chains),
        "linked_to_prime": linked,
        "enriched_from_prime_index": enriched,
        "declared_prime_only": declared,
        "linkage_rate": round(linkage_rate, 4),
        "enrichment_rate": round(enriched / len(chains), 4) if chains else 0.0,
        "full_chain_rate": round(full_chains / len(chains), 4) if chains else 0.0,
        "review_queue_count": len(review),
        "per_asset_count": len(by_asset),
        "per_municipality_count": len(by_muni),
        "outputs": [
            "data/staging/processed/execution/execution_chain_master.csv",
            "data/staging/processed/execution/execution_chain_per_asset.csv",
            "data/staging/processed/execution/execution_chain_per_municipality.csv",
            "data/staging/processed/execution/execution_chain_review_queue.csv",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    a = p.parse_args(argv)
    result = build_execution_chains(Path(a.root))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
