"""
FinancialData.net entity enrichment CLI — public-market identifier crosswalk.

Default mode: DRY-RUN with synthetic fixtures. Never calls the live API in this
mode. Live use requires both FINANCIALDATA_API_KEY and FINANCIALDATA_LICENSE_APPROVED
plus the `--live` flag.

Outputs (paths created relative to repo root by default):
  outputs/enrichment/financialdata_identifier_crosswalk.csv
  outputs/enrichment/financialdata_entity_matches.csv
  outputs/review/financialdata_match_review_queue.csv
  reports/financialdata_enrichment_readiness.json

Usage:
  python3 scripts/enrichment/enrich_financialdata_entities.py
  python3 scripts/enrichment/enrich_financialdata_entities.py --input <path>
  python3 scripts/enrichment/enrich_financialdata_entities.py --output-dir <path>
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from scripts.providers.financialdata_net import (  # noqa: E402
    PROVIDER_NAME,
    FinancialDataNetProvider,
    from_config,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

DEFAULT_INPUT_CANONICAL = PROJECT_ROOT / "data" / "processed" / "entities_resolved.csv"
DEFAULT_SYNTHETIC_FIXTURE = (
    PROJECT_ROOT / "tests" / "fixtures" / "financialdata_synthetic_entities.csv"
)

DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "outputs"

CROSSWALK_PATH = "enrichment/financialdata_identifier_crosswalk.csv"
MATCHES_PATH = "enrichment/financialdata_entity_matches.csv"
REVIEW_PATH = "review/financialdata_match_review_queue.csv"
READINESS_PATH = PROJECT_ROOT / "reports" / "financialdata_enrichment_readiness.json"

OUTPUT_COLUMNS = [
    "source_entity_id",
    "source_entity_name",
    "source_family",
    "provider",
    "provider_endpoint",
    "provider_identifier",
    "matched_name",
    "ticker",
    "cik",
    "lei",
    "cusip",
    "isin",
    "figi",
    "security_type",
    "industry",
    "website",
    "country",
    "match_method",
    "confidence",
    "review_required",
    "evidence_tier",
    "retrieved_at",
    "license_status",
    "raw_payload_stored",
]

DETERMINISTIC_IDENTIFIERS = ("cusip", "isin", "figi", "lei", "cik", "ticker")


# ----------------------------------------------------------------------------
# Synthetic candidate fixtures (dry-run mode only)
# ----------------------------------------------------------------------------
# Keyed by the post-normalize_name() form of the input entity name. Each value
# is a list of candidate (provider) records. Multiple candidates → ambiguous;
# one + identifier → match. To find the lookup key for an entity name, call
# normalize_name(name).
SYNTHETIC_CANDIDATES: dict[str, list[dict]] = {
    # normalize_name("AECOM") -> "AECOM"
    "AECOM": [
        {
            "matched_name": "AECOM",
            "ticker": "ACM",
            "cik": "0000868857",
            "cusip": "00766T100",
            "isin": "US00766T1007",
            "figi": "BBG000C2LZP3",
            "security_type": "common_stock",
            "industry": "engineering_services",
            "website": "https://aecom.com",
            "country": "US",
            "endpoint": "company_information",
        }
    ],
    # normalize_name("Fluor Corp") -> "FLUOR"
    "FLUOR": [
        {
            "matched_name": "Fluor Corp",
            "ticker": "FLR",
            "cik": "0001124198",
            "cusip": "343412102",
            "isin": "US3434121022",
            "figi": "BBG000BLT2W3",
            "security_type": "common_stock",
            "industry": "construction",
            "website": "https://fluor.com",
            "country": "US",
            "endpoint": "company_information",
        }
    ],
    # normalize_name("Parsons Corp") -> "PARSONS"
    "PARSONS": [
        {
            "matched_name": "Parsons Corp",
            "ticker": "PSN",
            "cik": "0001658766",
            "cusip": "70202L102",
            "isin": "US70202L1026",
            "figi": "BBG00P0QQXY7",
            "security_type": "common_stock",
            "industry": "engineering_services",
            "website": "https://parsons.com",
            "country": "US",
            "endpoint": "company_information",
        }
    ],
    # normalize_name("ACME Corporation") -> "ACME". Ambiguous: two candidates,
    # no disambiguating identifier on input → routes to review queue.
    "ACME": [
        {"matched_name": "ACME Corp (TX)", "ticker": "ACMEX", "endpoint": "company_information"},
        {
            "matched_name": "Acme Corp Holdings (NV)",
            "ticker": "ACMEH",
            "endpoint": "company_information",
        },
    ],
    # normalize_name("Black and Veatch Infrastructure Inc") -> "BLACK AND VEATCH INFRASTRUCTURE".
    # Fuzzy: candidate name doesn't exactly match input → routes to review queue.
    "BLACK AND VEATCH INFRASTRUCTURE": [
        {"matched_name": "Black & Veatch Holding Co.", "endpoint": "company_information"},
    ],
}


# ----------------------------------------------------------------------------
# Normalization + matching helpers
# ----------------------------------------------------------------------------

_NAME_PUNCT_RE = re.compile(r"[^A-Z0-9 ]+")
_NAME_SUFFIX_RE = re.compile(
    r"\b(INC|CORP|CORPORATION|LLC|LLP|LP|LTD|LIMITED|CO|COMPANY|HOLDINGS|HOLDING|GROUP|PLC|SA|AG|NV|BV)\b"
)


def normalize_name(name: str) -> str:
    """Uppercase, strip punctuation, collapse whitespace, drop common corporate suffixes."""
    s = (name or "").upper().strip()
    s = _NAME_PUNCT_RE.sub(" ", s)
    s = _NAME_SUFFIX_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _has_identifier(record: dict, key: str) -> bool:
    return bool((record.get(key) or "").strip())


@dataclass
class MatchResult:
    method: str  # see schema enum
    confidence: float
    review_required: bool
    evidence_tier: str  # T1/T2/T3/T4
    chosen: dict | None  # the candidate record we picked, or None
    endpoint: str  # provider_endpoint value


def route_match(entity: dict, candidates: list[dict]) -> MatchResult:
    """
    Decide how to route a candidate set for one input entity.

    Resolution order:
      1. Deterministic identifier match (CUSIP/ISIN/FIGI/LEI/CIK/ticker on both sides)
      2. Single exact normalized-name match (no conflicting identifiers)
      3. Ambiguous (multi-candidate) → review queue
      4. Single fuzzy-name candidate → review queue
      5. No candidates → not_public_market_resolved
    """
    if not candidates:
        return MatchResult(
            method="not_public_market_resolved",
            confidence=0.0,
            review_required=False,
            evidence_tier="T4",
            chosen=None,
            endpoint="none",
        )

    # 1) Deterministic identifier match
    for ident_key in DETERMINISTIC_IDENTIFIERS:
        entity_val = (entity.get(ident_key) or "").strip().upper()
        if not entity_val:
            continue
        for cand in candidates:
            cand_val = (cand.get(ident_key) or "").strip().upper()
            if cand_val and cand_val == entity_val:
                return MatchResult(
                    method=f"deterministic_{ident_key}",
                    confidence=1.0,
                    review_required=False,
                    evidence_tier="T1",
                    chosen=cand,
                    endpoint=cand.get("endpoint") or "company_information",
                )

    # 2) Single exact name match with no conflicting identifiers
    entity_norm = normalize_name(entity.get("name") or entity.get("source_entity_name") or "")
    exact = [c for c in candidates if normalize_name(c.get("matched_name") or "") == entity_norm]
    if len(exact) == 1 and len(candidates) == 1:
        chosen = exact[0]
        # If the single candidate carries identifiers, surface them at T2.
        any_ident = any(_has_identifier(chosen, k) for k in DETERMINISTIC_IDENTIFIERS)
        return MatchResult(
            method="exact_name",
            confidence=0.85,
            review_required=False,
            evidence_tier="T2" if any_ident else "T3",
            chosen=chosen,
            endpoint=chosen.get("endpoint") or "company_information",
        )

    # 3) Ambiguous multi-candidate
    if len(candidates) > 1:
        return MatchResult(
            method="ambiguous_multi",
            confidence=0.4,
            review_required=True,
            evidence_tier="T3",
            chosen=candidates[0],
            endpoint=candidates[0].get("endpoint") or "company_information",
        )

    # 4) Single fuzzy match
    chosen = candidates[0]
    any_ident = any(_has_identifier(chosen, k) for k in DETERMINISTIC_IDENTIFIERS)
    return MatchResult(
        method="fuzzy_name",
        confidence=0.55,
        review_required=True,
        evidence_tier="T2" if any_ident else "T4",
        chosen=chosen,
        endpoint=chosen.get("endpoint") or "company_information",
    )


# ----------------------------------------------------------------------------
# Row assembly
# ----------------------------------------------------------------------------


def build_output_row(
    entity: dict, result: MatchResult, license_status: str, retrieved_at: str
) -> dict:
    chosen = result.chosen or {}
    row = {
        "source_entity_id": str(entity.get("source_entity_id") or entity.get("entity_id") or ""),
        "source_entity_name": str(entity.get("name") or entity.get("source_entity_name") or ""),
        "source_family": str(entity.get("source_family") or entity.get("family") or ""),
        "provider": PROVIDER_NAME,
        "provider_endpoint": result.endpoint,
        "provider_identifier": str(
            chosen.get("provider_identifier") or chosen.get("ticker") or chosen.get("cik") or ""
        ),
        "matched_name": str(chosen.get("matched_name") or ""),
        "ticker": str(chosen.get("ticker") or ""),
        "cik": str(chosen.get("cik") or ""),
        "lei": str(chosen.get("lei") or ""),
        "cusip": str(chosen.get("cusip") or ""),
        "isin": str(chosen.get("isin") or ""),
        "figi": str(chosen.get("figi") or ""),
        "security_type": str(chosen.get("security_type") or ""),
        "industry": str(chosen.get("industry") or ""),
        "website": str(chosen.get("website") or ""),
        "country": str(chosen.get("country") or ""),
        "match_method": result.method,
        "confidence": round(float(result.confidence), 4),
        "review_required": bool(result.review_required),
        "evidence_tier": result.evidence_tier,
        "retrieved_at": retrieved_at,
        "license_status": license_status,
        "raw_payload_stored": False,
    }
    return row


# ----------------------------------------------------------------------------
# Input loading
# ----------------------------------------------------------------------------


def load_input_entities(path: Path) -> list[dict]:
    """Read CSV input entities. Returns list of dicts with normalized keys."""
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return rows


def lookup_candidates(
    entity: dict, *, dry_run: bool, provider: FinancialDataNetProvider | None = None
) -> list[dict]:
    """
    Resolve candidates for an entity.

    In dry-run mode: synthetic fixtures only, keyed by normalized name. No
    network. In live mode (not exercised in tests): the provider would be
    consulted, but only after readiness gating.
    """
    name = entity.get("name") or entity.get("source_entity_name") or ""
    key = normalize_name(name)
    if dry_run:
        return list(SYNTHETIC_CANDIDATES.get(key, []))
    # Live mode is intentionally a stub here — implementation deferred until
    # license is approved AND vendor docs confirm endpoint shapes.
    if provider is None or not provider.is_ready():
        return []
    # When implemented, call provider.company_information(name) etc., normalize
    # the response into the candidate shape used above, and return.
    return []


# ----------------------------------------------------------------------------
# Output writing
# ----------------------------------------------------------------------------


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            # CSV serialization: booleans as lowercase strings for stable readback.
            stable = dict(r)
            for bool_key in ("review_required", "raw_payload_stored"):
                stable[bool_key] = "true" if r.get(bool_key) else "false"
            w.writerow(stable)


def write_outputs(rows: list[dict], readiness: dict, output_dir: Path) -> dict[str, Path]:
    matched = [
        r
        for r in rows
        if not r["review_required"] and r["match_method"] != "not_public_market_resolved"
    ]
    review = [r for r in rows if r["review_required"]]
    # Crosswalk = matched rows that carry at least one identifier
    crosswalk = [r for r in matched if any((r.get(k) or "") for k in DETERMINISTIC_IDENTIFIERS)]
    paths = {
        "crosswalk": output_dir / CROSSWALK_PATH,
        "matches": output_dir / MATCHES_PATH,
        "review": output_dir / REVIEW_PATH,
        "readiness": READINESS_PATH,
    }
    _write_csv(paths["crosswalk"], crosswalk)
    _write_csv(paths["matches"], matched)
    _write_csv(paths["review"], review)
    paths["readiness"].parent.mkdir(parents=True, exist_ok=True)
    paths["readiness"].write_text(json.dumps(readiness, indent=2, sort_keys=True), encoding="utf-8")
    return paths


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------


def run(
    input_path: Path | None = None,
    output_dir: Path | None = None,
    dry_run: bool = True,
    provider: FinancialDataNetProvider | None = None,
) -> dict:
    if input_path is None:
        if DEFAULT_INPUT_CANONICAL.exists():
            input_path = DEFAULT_INPUT_CANONICAL
        else:
            input_path = DEFAULT_SYNTHETIC_FIXTURE
    if output_dir is None:
        output_dir = DEFAULT_OUTPUT_DIR

    if provider is None:
        provider = from_config()
    readiness_obj = provider.readiness()
    readiness_dict = readiness_obj.to_dict()
    readiness_dict["dry_run"] = bool(dry_run)
    readiness_dict["input_path"] = str(input_path)
    readiness_dict["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Live mode requires readiness; otherwise we fall back to dry-run automatically.
    if not dry_run and not readiness_obj.ready_for_live:
        readiness_dict["forced_dry_run"] = True
        readiness_dict["reason"] = (
            f"Provider not ready for live ({readiness_obj.status}); "
            "no live calls performed. Emitting empty outputs."
        )
        dry_run = True

    entities = load_input_entities(Path(input_path)) if Path(input_path).exists() else []

    license_status = readiness_obj.license_status
    retrieved_at = readiness_dict["timestamp"]

    rows: list[dict] = []
    for ent in entities:
        candidates = lookup_candidates(ent, dry_run=dry_run, provider=provider)
        result = route_match(ent, candidates)
        rows.append(build_output_row(ent, result, license_status, retrieved_at))

    paths = write_outputs(rows, readiness_dict, output_dir)

    summary = {
        "status": "OK" if readiness_obj.ready_for_live else "SKIPPED_OPTIONAL",
        "dry_run": bool(dry_run),
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "entity_count": len(entities),
        "matched": sum(
            1
            for r in rows
            if not r["review_required"] and r["match_method"] != "not_public_market_resolved"
        ),
        "review": sum(1 for r in rows if r["review_required"]),
        "unmatched": sum(1 for r in rows if r["match_method"] == "not_public_market_resolved"),
        "readiness": readiness_dict,
        "outputs": {k: str(v) for k, v in paths.items()},
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="FinancialData.net entity enrichment (OPTIONAL; default dry-run/mock).",
    )
    parser.add_argument("--input", default=None, help="Path to canonical entity CSV")
    parser.add_argument("--output-dir", default=None, help="Output dir (default: outputs/)")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Attempt live calls (requires FINANCIALDATA_API_KEY and "
        "FINANCIALDATA_LICENSE_APPROVED). Default is dry-run.",
    )
    args = parser.parse_args()

    result = run(
        input_path=Path(args.input) if args.input else None,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        dry_run=not args.live,
    )
    print(json.dumps({k: v for k, v in result.items() if k != "readiness"}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
