"""Entity resolution orchestration for MoneySweep.

Discovery is offline-first and may use name similarity to generate candidates, but
canonical identity adjudication is delegated to
``moneysweep.capital_control.resolution_core``. Name similarity, normalization,
proximity, or source absence never establishes identity.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from moneysweep.capital_control.resolution_core import (
    Candidate,
    CertificationState,
    EvidenceBasis,
    resolve_candidates,
)
from scripts.config import PROJECT_ROOT, setup_logging
from scripts.sam_enrichment import normalize_vendor, name_similarity

USAS_RECIPIENT_SEARCH = "https://api.usaspending.gov/api/v2/recipient/search/"
USAS_RECIPIENT_DETAIL = "https://api.usaspending.gov/api/v2/recipient/{hash_or_id}/"
RATE_DELAY = 0.3
MATCH_THRESHOLD = 0.75
TOP_N_DEFAULT = 10_000


def _http_post(url: str, payload: dict, timeout: int = 12) -> dict | None:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode())
    except Exception:
        return None
    return None


def _http_get(url: str, timeout: int = 12) -> dict | None:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status == 200:
                return json.loads(resp.read().decode())
    except Exception:
        return None
    return None


def search_recipient(vendor_name: str) -> dict | None:
    """Return the best USASpending *discovery candidate* by name similarity.

    This function deliberately does not certify identity. ``resolve_vendor``
    must pass the result through resolution_core before any parent is accepted.
    """
    norm = normalize_vendor(vendor_name)
    payload = {"search_text": vendor_name, "order": "desc", "sort": "amount", "limit": 5}
    data = _http_post(USAS_RECIPIENT_SEARCH, payload)
    if not data:
        return None
    results = data.get("results", [])
    best: dict | None = None
    best_score = 0.0
    for row in results:
        result_name = row.get("name") or row.get("recipient_name", "")
        score = name_similarity(norm, normalize_vendor(result_name))
        if score > best_score:
            best_score, best = score, row
    if best and best_score >= MATCH_THRESHOLD:
        best = dict(best)
        best["match_score"] = round(best_score, 3)
        return best
    return None


def get_recipient_detail(recipient_id: str) -> dict | None:
    return _http_get(USAS_RECIPIENT_DETAIL.format(hash_or_id=recipient_id))


def load_vendor_rankings(root: Path, top_n: int) -> list[dict]:
    enriched = root / "data" / "staging" / "processed" / "enrichment" / "master_enriched.csv"
    master = root / "data" / "staging" / "processed" / "pr_contracts_master.csv"
    unified = root / "data" / "staging" / "processed" / "pr_all_awards_master.csv"
    source_path = enriched if enriched.exists() else (master if master.exists() else unified)
    if not source_path.exists():
        raise FileNotFoundError(f"No master CSV found at {source_path}")

    vendor_totals: dict[str, dict] = {}
    with open(source_path, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            vendor_name = (row.get("vendor_name") or row.get("recipient_name") or "").strip()
            if not vendor_name:
                continue
            try:
                amount = float(row.get("obligated_amount") or 0)
            except (ValueError, TypeError):
                amount = 0.0
            item = vendor_totals.setdefault(
                vendor_name,
                {
                    "vendor_name": vendor_name,
                    "total_obligation": 0.0,
                    "record_count": 0,
                    "known_uei": (row.get("recipient_uei") or "").strip(),
                    "known_parent_uei": (row.get("parent_uei") or "").strip(),
                    "known_parent_name": (row.get("parent_name") or "").strip(),
                },
            )
            item["total_obligation"] += amount
            item["record_count"] += 1
            if not item["known_uei"]:
                item["known_uei"] = (row.get("recipient_uei") or "").strip()

    ranked = sorted(vendor_totals.values(), key=lambda item: item["total_obligation"], reverse=True)
    return ranked[:top_n]


def load_sam_index(root: Path) -> dict[str, dict]:
    path = root / "data" / "staging" / "processed" / "enrichment" / "vendor_uei_index.csv"
    if not path.exists():
        return {}
    index: dict[str, dict] = {}
    with open(path, encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            vendor_name = (row.get("vendor_name") or "").strip()
            if vendor_name:
                index[vendor_name] = row
                index.setdefault(normalize_vendor(vendor_name), row)
    return index


def _candidate_id(search: dict) -> str:
    return str(
        search.get("uei")
        or search.get("recipient_hash")
        or search.get("id")
        or search.get("name")
        or search.get("recipient_name")
        or "USASPENDING_CANDIDATE"
    )


def adjudicate_usaspending_candidate(vendor: dict, search: dict):
    """Adjudicate a discovery candidate without promoting name similarity.

    A USASpending candidate can PASS here only when the input already carries a
    stable UEI and the candidate independently reports the same UEI. All other
    name-search results remain CANDIDATE_NOT_IDENTITY.
    """
    known_uei = (vendor.get("known_uei") or "").strip()
    candidate_uei = (search.get("uei") or "").strip()
    basis = (
        EvidenceBasis.STABLE_ID
        if known_uei and candidate_uei and known_uei == candidate_uei
        else EvidenceBasis.HEURISTIC_DISCOVERY_ONLY
    )
    return resolve_candidates(
        [Candidate(_candidate_id(search), basis, "USASpending recipient search candidate")]
    )


def _safe_sam_parent(vendor: dict, sam_index: dict) -> tuple[dict | None, str]:
    """Return a SAM row only when binding evidence is available.

    Exact RAW-key lookup is accepted as an existing authoritative source
    manifestation. A normalized-name-only lookup is discovery unless a known UEI
    matches the SAM UEI exactly.
    """
    vendor_name = vendor["vendor_name"]
    exact = sam_index.get(vendor_name)
    if exact:
        return exact, "AUTHORITATIVE_BINDING"

    normalized = sam_index.get(normalize_vendor(vendor_name))
    if not normalized:
        return None, "NONE"
    known_uei = (vendor.get("known_uei") or "").strip()
    sam_uei = (normalized.get("uei") or "").strip()
    if known_uei and sam_uei and known_uei == sam_uei:
        return normalized, "STABLE_ID"
    return None, "HEURISTIC_DISCOVERY_ONLY"


def resolve_vendor(
    vendor: dict,
    sam_index: dict,
    cache: dict,
    logger,
    *,
    use_api: bool = False,
) -> dict:
    vendor_name = vendor["vendor_name"]
    result = {
        "vendor_name": vendor_name,
        "rank": vendor.get("_rank", 0),
        "total_obligation": vendor["total_obligation"],
        "record_count": vendor["record_count"],
        "uei": vendor.get("known_uei", ""),
        "parent_uei": vendor.get("known_parent_uei", ""),
        "parent_name": vendor.get("known_parent_name", ""),
        "business_types": "",
        "match_confidence": 0.0,
        "identity_status": "UNRESOLVED",
        "binding_basis": "NONE",
        "candidate_uei": "",
        "source": "none",
    }

    # Existing parent fields are source-backed manifestations. Keep them intact;
    # the canonical core remains responsible for cross-source entity federation.
    if result["parent_uei"] or result["parent_name"]:
        result["identity_status"] = "PASS"
        result["binding_basis"] = "AUTHORITATIVE_BINDING"
        result["source"] = "sam_enrichment"
        return result

    sam_row, sam_basis = _safe_sam_parent(vendor, sam_index)
    if sam_row and sam_row.get("parent_uei"):
        result["uei"] = sam_row.get("uei", result["uei"])
        result["parent_uei"] = sam_row["parent_uei"]
        result["parent_name"] = sam_row.get("parent_name", "")
        result["match_confidence"] = float(sam_row.get("match_score") or 0)
        result["identity_status"] = "PASS"
        result["binding_basis"] = sam_basis
        result["source"] = "sam_index"
        return result
    if sam_row and sam_row.get("resolution_status") == "RESOLVED_LOCAL_GOV":
        result["identity_status"] = "PASS"
        result["binding_basis"] = sam_basis
        result["source"] = "local_government"
        return result

    if vendor_name in cache:
        cached = cache[vendor_name]
        if not use_api or cached.get("parent_uei") or cached.get("parent_name"):
            result.update(cached)
            result.setdefault("identity_status", "PROVISIONAL")
            result.setdefault("binding_basis", "AUTHORITATIVE_BINDING")
            result["source"] = "cache"
            return result

    if not use_api:
        result["source"] = "offline_unresolved"
        return result

    time.sleep(RATE_DELAY)
    search = search_recipient(vendor_name)
    if not search:
        result["source"] = "unresolved"
        cache[vendor_name] = {
            "parent_uei": "",
            "parent_name": "",
            "uei": result["uei"],
            "identity_status": "UNRESOLVED",
            "binding_basis": "NONE",
        }
        return result

    result["match_confidence"] = search.get("match_score", 0.0)
    result["candidate_uei"] = search.get("uei", "")
    adjudication = adjudicate_usaspending_candidate(vendor, search)
    result["identity_status"] = adjudication.state.value
    result["binding_basis"] = (
        "STABLE_ID" if adjudication.state is CertificationState.PASS else "HEURISTIC_DISCOVERY_ONLY"
    )

    if adjudication.state is not CertificationState.PASS:
        result["source"] = "usaspending_candidate_not_identity"
        # Preserve the candidate but do not fetch/promote its parent.
        cache[vendor_name] = {
            "parent_uei": "",
            "parent_name": "",
            "uei": result["uei"],
            "candidate_uei": result["candidate_uei"],
            "identity_status": result["identity_status"],
            "binding_basis": result["binding_basis"],
        }
        return result

    if not result["uei"]:
        result["uei"] = search.get("uei", "")
    recipient_id = search.get("recipient_hash") or search.get("id", "")
    if recipient_id:
        time.sleep(RATE_DELAY)
        detail = get_recipient_detail(recipient_id)
        if detail:
            parents = detail.get("parents") or []
            if parents:
                parent = parents[0] if isinstance(parents, list) else parents
                result["parent_uei"] = parent.get("uei", "") or parent.get("recipient_uei", "")
                result["parent_name"] = parent.get("name", "") or parent.get("recipient_name", "")
            if not result["parent_uei"]:
                result["parent_uei"] = detail.get("parent_uei", "")
                result["parent_name"] = detail.get("parent_name", "")
            business_types = detail.get("business_types_description") or detail.get(
                "business_types", []
            )
            result["business_types"] = (
                "; ".join(business_types)
                if isinstance(business_types, list)
                else str(business_types)
            )

    result["source"] = "usaspending_stable_id_bound"
    cache[vendor_name] = {
        "parent_uei": result["parent_uei"],
        "parent_name": result["parent_name"],
        "uei": result["uei"],
        "business_types": result["business_types"],
        "identity_status": result["identity_status"],
        "binding_basis": result["binding_basis"],
    }
    logger.info(
        f"  {vendor_name[:45]:<45} parent={result['parent_name'][:30] or '—':<30} "
        f"state={result['identity_status']}"
    )
    return result


def run(
    root: Path | None = None,
    top_n: int = TOP_N_DEFAULT,
    resume: bool = False,
    *,
    use_api: bool = False,
    max_api: int = 100,
) -> Path:
    del resume  # accepted for CLI compatibility; cache is always read when present.
    root = root or PROJECT_ROOT
    output_dir = root / "data" / "staging" / "processed" / "enrichment"
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_path = output_dir / "entity_cache.json"
    out_path = output_dir / "entity_hierarchy.csv"

    logger = setup_logging("entity_resolution")
    if use_api and max_api < 1:
        raise ValueError("max_api must be at least 1")

    vendors = load_vendor_rankings(root, top_n)
    sam_index = load_sam_index(root)
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}

    rows: list[dict] = []
    for rank, vendor in enumerate(vendors, 1):
        vendor["_rank"] = rank
        rows.append(resolve_vendor(vendor, sam_index, cache, logger, use_api=False))

    api_calls = 0
    if use_api:
        for index, (vendor, current) in enumerate(zip(vendors, rows, strict=True)):
            if current.get("parent_uei") or current.get("parent_name"):
                continue
            if current.get("source") == "local_government":
                continue
            if api_calls >= max_api:
                break
            rows[index] = resolve_vendor(vendor, sam_index, cache, logger, use_api=True)
            api_calls += 1

    cache_path.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    fieldnames = [
        "rank",
        "vendor_name",
        "total_obligation",
        "record_count",
        "uei",
        "parent_uei",
        "parent_name",
        "business_types",
        "match_confidence",
        "identity_status",
        "binding_basis",
        "candidate_uei",
        "source",
    ]
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    logger.info(f"Entity hierarchy written: {out_path}; live API calls={api_calls}")
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description="MoneySweep entity-resolution orchestration")
    parser.add_argument("--top", type=int, default=TOP_N_DEFAULT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--use-api", action="store_true")
    parser.add_argument("--max-api", type=int, default=100)
    args = parser.parse_args()
    run(top_n=args.top, resume=args.resume, use_api=args.use_api, max_api=args.max_api)
    return 0


if __name__ == "__main__":
    sys.exit(main())
