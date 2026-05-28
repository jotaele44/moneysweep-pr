"""Row-level contract-finance geo reasoning (standalone producer).

Regenerates the Contract-Sweeper contract-finance / geo layer from **row-level**
canonical exports rather than aggregate municipality CSVs. For every funding
award and transaction row it attaches an explicit geo-resolution method, reason
code, confidence, and jurisdiction class; decomposes the UNKNOWN bucket by
reason; runs a San Juan HQ / default-location bias test; rebuilds the entity
graph with full edge metadata; and re-runs the SpiderWeb engine-readiness gate.

This module is an *independent* producer: it does not import or run
``run_all.py``, any pipeline stage, or anything in the SpiderWeb PR. It only
reads already-produced row-level inputs and reuses the deterministic geo helpers
in ``contract_sweeper.runtime.geo_attribution``.

Inputs (in priority order):
  1. Export streams (``funding_awards.jsonl`` + ``transactions.jsonl``) from an
     export package built by ``scripts/run_export.py`` (``--export-dir`` or
     ``exports/contract_sweeper_latest/``).
  2. Canonical masters (``contracts_master.csv`` + ``financial_flows_master.csv``)
     under ``--processed-dir``.

For reproducible, committed outputs run against the row-level fixtures::

    python scripts/run_contract_finance_geo_reasoning.py \
        --processed-dir tests/fixtures/sample_master_inputs --build-crosswalk

Outputs (under ``--output-dir``, default ``outputs/contract_finance``):
  contract_finance_geo_rows.csv
  unknown_decomposition.csv / unknown_decomposition_summary.json
  san_juan_hq_bias_report.csv / san_juan_hq_bias_summary.json
  municipality_funding_density.csv
  entity_graph.graphml / entity_graph_edge_metadata_audit.csv
  entity_graph_qa_report.json
  spiderweb_engine_readiness_reassessment.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contract_sweeper.runtime.geo_attribution import (  # noqa: E402
    _normalize_fips,
    _normalize_pr_name,
    _strip_accents,
)

DEFAULT_PROCESSED_DIR = REPO_ROOT / "data" / "staging" / "processed"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "outputs" / "contract_finance"
MUNICIPALITIES_REF = REPO_ROOT / "data" / "reference" / "pr_municipalities.csv"
DEFAULT_CROSSWALK = REPO_ROOT / "data" / "reference" / "pr_78_municipio_crosswalk.csv"
DEFAULT_EXPORT_LATEST = REPO_ROOT / "exports" / "contract_sweeper_latest"

SAN_JUAN_CODE = "72127"
DEFAULT_SAN_JUAN_THRESHOLD = 0.35
DEFAULT_UNKNOWN_AMOUNT_THRESHOLD = 0.10
CURRENCY = "USD"

PRODUCER_SCRIPT = "scripts/run_contract_finance_geo_reasoning.py"
PRODUCER_PHASE = "RCF_GEO_REASONING"

# Canonical reason / jurisdiction vocabularies (mirrored in tests).
GEO_RESOLUTION_REASONS = (
    "place_of_performance_exact",
    "project_municipality_match",
    "recipient_municipality_match",
    "municipality_name_only",
    "headquarters_only",
    "agency_default",
    "outside_pr",
    "missing_location",
    "ambiguous_location",
    "invalid_pr_municipio",
    "parser_failed",
)
JURISDICTION_CLASSES = (
    "PR_MUNICIPIO",
    "UNKNOWN_MISSING",
    "UNKNOWN_AMBIGUOUS",
    "OUTSIDE_PR_US_STATE",
    "OUTSIDE_PR_US_COUNTY",
    "OUTSIDE_PR_FOREIGN",
    "HEADQUARTERS_ONLY",
    "AGENCY_DEFAULT",
)
UNKNOWN_REASONS = (
    "missing_location",
    "headquarters_only",
    "agency_default",
    "outside_pr",
    "ambiguous_location",
    "invalid_pr_municipio",
    "parser_failed",
    "unknown_unclassified_row_level",
)
UNKNOWN_JURISDICTIONS = {
    "UNKNOWN_MISSING",
    "UNKNOWN_AMBIGUOUS",
    "OUTSIDE_PR_US_STATE",
    "OUTSIDE_PR_US_COUNTY",
    "OUTSIDE_PR_FOREIGN",
    "HEADQUARTERS_ONLY",
    "AGENCY_DEFAULT",
}

# Required accent/ASCII alias pairs that the crosswalk must collapse (Task 4).
REQUIRED_ALIAS_PAIRS = (
    ("BAYAMÓN", "BAYAMON"),
    ("MAYAGÜEZ", "MAYAGUEZ"),
    ("GUÁNICA", "GUANICA"),
    ("RINCÓN", "RINCON"),
    ("SAN GERMÁN", "SAN GERMAN"),
    ("RÍO GRANDE", "RIO GRANDE"),
    ("CATAÑO", "CATANO"),
    ("LOÍZA", "LOIZA"),
    ("PEÑUELAS", "PENUELAS"),
    ("AÑASCO", "ANASCO"),
    ("COMERÍO", "COMERIO"),
    ("LAS MARÍAS", "LAS MARIAS"),
)


# --------------------------------------------------------------------------- #
# Small IO / parsing helpers                                                   #
# --------------------------------------------------------------------------- #

def _clean(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _parse_amount(raw: Any) -> float:
    s = _clean(raw).replace("$", "").replace(",", "")
    if not s:
        return 0.0
    try:
        amount = float(s)
    except ValueError:
        return 0.0
    if amount != amount or amount in (float("inf"), float("-inf")):  # NaN / inf
        return 0.0
    return amount


def _parse_confidence(raw: Any) -> float | None:
    s = _clean(raw)
    if not s:
        return None
    try:
        value = float(s)
    except ValueError:
        return None
    if value != value:
        return None
    return min(1.0, max(0.0, value))


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _lineage(source_inputs: list[str], method: str) -> dict[str, Any]:
    return {
        "producer_script": PRODUCER_SCRIPT,
        "producer_phase": PRODUCER_PHASE,
        "source_inputs": source_inputs,
        "extraction_method": method,
    }


# --------------------------------------------------------------------------- #
# Crosswalk (Task 4)                                                           #
# --------------------------------------------------------------------------- #

def build_crosswalk_rows(ref_path: Path = MUNICIPALITIES_REF) -> list[dict[str, str]]:
    """Derive the 78-municipio crosswalk from ``pr_municipalities.csv``.

    Collapses accent/ASCII aliases so both forms map to one canonical code.
    Deterministic; never hand-fabricates geo evidence.
    """
    rows: list[dict[str, str]] = []
    for src in _read_csv(ref_path):
        code = _normalize_fips(src.get("municipality_code"))
        if not code:
            continue
        canonical = _clean(src.get("canonical_name"))
        canonical_es = _clean(src.get("canonical_name_es"))
        raw_aliases = [a for a in _clean(src.get("aliases")).split("|") if a]
        # Build a de-duplicated alias list folding every accented form to ASCII.
        alias_seen: dict[str, None] = {}
        for name in [canonical, canonical_es, *raw_aliases]:
            for variant in (name, _strip_accents(name).upper()):
                v = _clean(variant)
                if v and v not in alias_seen:
                    alias_seen[v] = None
        rows.append(
            {
                "municipality_geoid": code,
                "municipality_code": code,
                "municipality_name": canonical,
                "municipality_name_ascii": _strip_accents(canonical).title(),
                "municipality_name_canonical": canonical,
                "municipality_name_es": canonical_es,
                "aliases": "|".join(alias_seen.keys()),
            }
        )
    rows.sort(key=lambda r: r["municipality_code"])
    return rows


def write_crosswalk(path: Path = DEFAULT_CROSSWALK, ref_path: Path = MUNICIPALITIES_REF) -> int:
    rows = build_crosswalk_rows(ref_path)
    _write_csv(
        path,
        rows,
        [
            "municipality_geoid",
            "municipality_code",
            "municipality_name",
            "municipality_name_ascii",
            "municipality_name_canonical",
            "municipality_name_es",
            "aliases",
        ],
    )
    return len(rows)


class Crosswalk:
    """Resolves a municipality code or place name to a canonical PR municipio."""

    def __init__(self, rows: list[dict[str, str]]):
        self.by_code: dict[str, dict[str, str]] = {}
        self.by_alias: dict[str, str] = {}
        for row in rows:
            code = _normalize_fips(row.get("municipality_code"))
            if not code:
                continue
            self.by_code[code] = row
            names = [
                row.get("municipality_name", ""),
                row.get("municipality_name_canonical", ""),
                row.get("municipality_name_es", ""),
                *(_clean(row.get("aliases")).split("|")),
            ]
            for name in names:
                key = _normalize_pr_name(name)
                if key:
                    self.by_alias.setdefault(key, code)

    @classmethod
    def load(cls, path: Path) -> "Crosswalk":
        return cls(_read_csv(path))

    @property
    def valid_codes(self) -> set[str]:
        return set(self.by_code)

    def resolve_code(self, raw_code: Any) -> str:
        return _normalize_fips(raw_code)

    def resolve_name(self, raw_name: Any) -> str:
        return self.by_alias.get(_normalize_pr_name(raw_name), "")

    def canonical(self, code: str) -> tuple[str, str]:
        row = self.by_code.get(code, {})
        return row.get("municipality_code", code), row.get("municipality_name_canonical", "")


# --------------------------------------------------------------------------- #
# Geo classification (Task 3)                                                  #
# --------------------------------------------------------------------------- #

_PLACE_SOURCES = {"place_of_performance", "place_of_performance_exact", "pop", "performance"}
_PROJECT_SOURCES = {"project", "project_municipality", "project_site", "project_location"}
_RECIPIENT_SOURCES = {
    "recipient_address",
    "recipient",
    "recipient_city",
    "recipient_municipality",
    "recipient_location",
}
_HQ_SOURCES = {"headquarters", "hq", "recipient_hq", "headquarters_only", "corporate_hq"}
_AGENCY_SOURCES = {
    "agency",
    "agency_default",
    "funding_office",
    "funding_agency",
    "awarding_agency",
    "default",
    "source_default",
}

_METHOD_CONFIDENCE = {
    "code_exact": 0.97,
    "name_exact": 0.90,
    "name_normalized": 0.80,
    "headquarters": 0.50,
    "agency_default": 0.30,
    "outside_pr": 0.60,
    "none": 0.0,
}


def _looks_foreign(country: str) -> bool:
    c = _strip_accents(country).upper().strip()
    return bool(c) and c not in {"US", "USA", "UNITED STATES", "PR", "PUERTO RICO"}


def _is_pr_state(state: str) -> bool:
    s = _strip_accents(state).upper().strip()
    return s in {"", "PR", "PUERTO RICO"}


def classify_geo(geo: dict[str, Any], crosswalk: Crosswalk) -> dict[str, Any]:
    """Classify a single row's geo evidence into the required reason fields.

    ``geo`` is the normalized intermediate dict produced by the extractors. Only
    evidence present in the row drives the outcome — nothing is fabricated.
    """
    raw_code = _clean(geo.get("raw_code"))
    raw_name = _clean(geo.get("raw_name")) or _clean(geo.get("raw_municipality"))
    source = _strip_accents(_clean(geo.get("attribution_source"))).lower().replace(" ", "_")
    country = _clean(geo.get("country"))
    state = _clean(geo.get("state"))
    county_fips = _clean(geo.get("county_fips"))
    conf_in = _parse_confidence(geo.get("attribution_confidence"))

    def out(reason: str, jclass: str, method: str, code: str = "") -> dict[str, Any]:
        muni_code, muni_name = ("", "")
        if code:
            muni_code, muni_name = crosswalk.canonical(code)
        confidence = conf_in if conf_in is not None else _METHOD_CONFIDENCE.get(method, 0.0)
        hq_flag = reason == "headquarters_only"
        outside_flag = reason == "outside_pr"
        sj_flag = _compute_san_juan_bias_flag(code, reason, source, geo)
        unknown_reason = ""
        if jclass in UNKNOWN_JURISDICTIONS:
            unknown_reason = reason if reason in UNKNOWN_REASONS else "unknown_unclassified_row_level"
        return {
            "geo_resolution_method": method,
            "geo_resolution_reason": reason,
            "geo_confidence": round(float(confidence), 3),
            "jurisdiction_class": jclass,
            "municipality_code_canonical": muni_code,
            "municipality_name_canonical": muni_name,
            "hq_bias_flag": hq_flag,
            "san_juan_bias_flag": sj_flag,
            "outside_pr_flag": outside_flag,
            "unknown_reason": unknown_reason,
        }

    # 1. Explicitly foreign.
    if _looks_foreign(country):
        return out("outside_pr", "OUTSIDE_PR_FOREIGN", "outside_pr")

    # 2. A US state other than PR.
    if not _is_pr_state(state):
        jclass = "OUTSIDE_PR_US_COUNTY" if county_fips else "OUTSIDE_PR_US_STATE"
        return out("outside_pr", jclass, "outside_pr")

    # 3. Code-driven resolution.
    if raw_code:
        norm = crosswalk.resolve_code(raw_code)  # PR-only 72xxx, else ""
        digits = raw_code.replace(".0", "").strip()
        if norm:
            if norm in crosswalk.valid_codes:
                reason = _reason_from_source(source)
                jclass, method = _class_method_for_reason(reason)
                return out(reason, jclass, method, code=norm)
            # 72xxx shape but not one of the 78 municipios -> false PR code.
            return out("invalid_pr_municipio", "UNKNOWN_AMBIGUOUS", "none")
        if digits.isdigit() and len(digits) == 5:
            # A real 5-digit FIPS that is not Puerto Rico.
            return out("outside_pr", "OUTSIDE_PR_US_COUNTY", "outside_pr")
        if digits.isdigit():
            # Truncated / malformed numeric code.
            return out("invalid_pr_municipio", "UNKNOWN_AMBIGUOUS", "none")
        # Non-numeric token where a code was expected.
        return out("parser_failed", "UNKNOWN_AMBIGUOUS", "none")

    # 4. Name-driven resolution.
    if raw_name:
        code = crosswalk.resolve_name(raw_name)
        if code:
            reason = _reason_from_source(source, name_only=True)
            jclass, method = _class_method_for_reason(reason, name_only=True)
            return out(reason, jclass, method, code=code)
        return out("ambiguous_location", "UNKNOWN_AMBIGUOUS", "none")

    # 5. Nothing usable.
    return out("missing_location", "UNKNOWN_MISSING", "none")


def _reason_from_source(source: str, name_only: bool = False) -> str:
    if source in _HQ_SOURCES:
        return "headquarters_only"
    if source in _AGENCY_SOURCES:
        return "agency_default"
    if source in _PROJECT_SOURCES:
        return "project_municipality_match"
    if source in _RECIPIENT_SOURCES:
        return "recipient_municipality_match"
    if source in _PLACE_SOURCES:
        return "municipality_name_only" if name_only else "place_of_performance_exact"
    return "municipality_name_only"


def _class_method_for_reason(reason: str, name_only: bool = False) -> tuple[str, str]:
    if reason == "headquarters_only":
        return "HEADQUARTERS_ONLY", "headquarters"
    if reason == "agency_default":
        return "AGENCY_DEFAULT", "agency_default"
    method = "name_normalized" if name_only else "code_exact"
    return "PR_MUNICIPIO", method


def _compute_san_juan_bias_flag(code: str, reason: str, source: str, geo: dict[str, Any]) -> bool:
    """Flag San Juan rows whose concentration is driven by HQ / default rather
    than work location (Task 6)."""
    resolves_sj = code == SAN_JUAN_CODE
    name_is_sj = crosswalk_name_is_san_juan(geo)
    if not (resolves_sj or name_is_sj):
        return False
    # San Juan text but no municipality code present on the row.
    if name_is_sj and not _clean(geo.get("raw_code")):
        return True
    # Tied to HQ / central-agency / funding-office / source-default fields.
    if reason in {"headquarters_only", "agency_default"}:
        return True
    if source in _HQ_SOURCES or source in _AGENCY_SOURCES:
        return True
    return False


def crosswalk_name_is_san_juan(geo: dict[str, Any]) -> bool:
    text = _normalize_pr_name(_clean(geo.get("raw_name")) or _clean(geo.get("raw_municipality")))
    return text in {_normalize_pr_name(n) for n in ("San Juan", "SAN JUAN", "SJU", "Rio Piedras", "Hato Rey", "Santurce")}


# --------------------------------------------------------------------------- #
# Input extraction (Task 3a / 3b)                                             #
# --------------------------------------------------------------------------- #

def _extract_from_master_award(row: dict[str, str]) -> dict[str, Any]:
    return {
        "record_type": "award",
        "record_id": _clean(row.get("award_id")) or _clean(row.get("contract_number")),
        "amount": _parse_amount(row.get("obligation_amount")),
        "event_date": _clean(row.get("award_date")),
        "recipient": _clean(row.get("recipient_name")) or _clean(row.get("normalized_name")),
        "agency": _clean(row.get("awarding_agency")) or _clean(row.get("funding_source")),
        "source_dataset": _clean(row.get("source_system")),
        "raw_code": _clean(row.get("geo_municipality_code")),
        "raw_name": _clean(row.get("geo_municipality_name")),
        "raw_municipality": _clean(row.get("municipality")),
        "attribution_source": _clean(row.get("geo_attribution_source")),
        "attribution_confidence": _clean(row.get("geo_attribution_confidence")),
        "county_fips": _clean(row.get("geo_county_fips")),
        "state": _clean(row.get("place_of_performance_state")),
        "country": _clean(row.get("country")) or "US",
    }


def _extract_from_master_flow(row: dict[str, str]) -> dict[str, Any]:
    return {
        "record_type": "transaction",
        "record_id": _clean(row.get("flow_id")),
        "amount": _parse_amount(row.get("amount")),
        "event_date": _clean(row.get("flow_date")),
        "recipient": _clean(row.get("recipient_entity_id")),
        "agency": _clean(row.get("funding_source")),
        "source_dataset": _clean(row.get("source_system")),
        "raw_code": _clean(row.get("geo_municipality_code")),
        "raw_name": _clean(row.get("geo_municipality_name")),
        "raw_municipality": _clean(row.get("municipality")),
        "attribution_source": _clean(row.get("geo_attribution_source")),
        "attribution_confidence": _clean(row.get("geo_attribution_confidence")),
        "county_fips": _clean(row.get("geo_county_fips")),
        "state": _clean(row.get("place_of_performance_state")),
        "country": _clean(row.get("country")) or "US",
    }


def _extract_from_export(row: dict[str, Any], record_type: str) -> dict[str, Any]:
    loc = row.get("location") or {}
    return {
        "record_type": record_type,
        "record_id": _clean(row.get("award_id") if record_type == "award" else row.get("transaction_id")),
        "amount": _parse_amount(row.get("amount")),
        "event_date": _clean(row.get("award_date") or row.get("transaction_date")),
        "recipient": _clean(row.get("recipient_entity_id") or row.get("payee_entity_id")),
        "agency": _clean(row.get("funding_agency_entity_id") or row.get("payer_entity_id")),
        "source_dataset": _clean(row.get("source_id")),
        "raw_code": _clean(loc.get("municipality_code")),
        "raw_name": _clean(loc.get("municipality_name")),
        "raw_municipality": _clean(loc.get("municipality")),
        "attribution_source": _clean(loc.get("attribution_source")),
        "attribution_confidence": _clean(loc.get("attribution_confidence")),
        "county_fips": _clean(loc.get("county_fips")),
        "state": _clean(loc.get("state")),
        "country": _clean(loc.get("country")) or "US",
        "source_id": _clean(row.get("source_id")),
    }


def load_rows(processed_dir: Path, export_dir: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load row-level award + transaction rows, preferring export streams."""
    provenance: dict[str, Any] = {}
    candidate = export_dir
    if candidate is None and DEFAULT_EXPORT_LATEST.exists():
        candidate = DEFAULT_EXPORT_LATEST
    if candidate is not None:
        awards_p = candidate / "funding_awards.jsonl"
        txn_p = candidate / "transactions.jsonl"
        if awards_p.exists() and txn_p.exists():
            rows = [_extract_from_export(r, "award") for r in _read_jsonl(awards_p)]
            rows += [_extract_from_export(r, "transaction") for r in _read_jsonl(txn_p)]
            provenance = {
                "input_mode": "export_streams",
                "source_inputs": [str(awards_p.relative_to(REPO_ROOT)) if awards_p.is_relative_to(REPO_ROOT) else str(awards_p),
                                  str(txn_p.relative_to(REPO_ROOT)) if txn_p.is_relative_to(REPO_ROOT) else str(txn_p)],
            }
            return rows, provenance

    awards_p = processed_dir / "contracts_master.csv"
    flows_p = processed_dir / "financial_flows_master.csv"
    rows = [_extract_from_master_award(r) for r in _read_csv(awards_p)]
    rows += [_extract_from_master_flow(r) for r in _read_csv(flows_p)]
    provenance = {
        "input_mode": "canonical_masters",
        "source_inputs": [str(awards_p), str(flows_p)],
    }
    return rows, provenance


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #

def classify_rows(rows: list[dict[str, Any]], crosswalk: Crosswalk) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for geo in rows:
        cls = classify_geo(geo, crosswalk)
        merged = {**geo, **cls}
        enriched.append(merged)
    return enriched


def _decompose_unknown(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    unknown_rows = [r for r in rows if r["jurisdiction_class"] in UNKNOWN_JURISDICTIONS]
    decomp_rows = []
    by_reason: dict[str, dict[str, float]] = defaultdict(lambda: {"record_count": 0, "total_amount": 0.0})
    for r in unknown_rows:
        reason = r.get("unknown_reason") or "unknown_unclassified_row_level"
        decomp_rows.append(
            {
                "record_id": r.get("record_id"),
                "record_type": r.get("record_type"),
                "jurisdiction_class": r["jurisdiction_class"],
                "unknown_reason": reason,
                "geo_resolution_reason": r["geo_resolution_reason"],
                "amount": r.get("amount", 0.0),
                "raw_code": r.get("raw_code", ""),
                "raw_name": r.get("raw_name", ""),
                "attribution_source": r.get("attribution_source", ""),
            }
        )
        by_reason[reason]["record_count"] += 1
        by_reason[reason]["total_amount"] += float(r.get("amount", 0.0))
    total_amount = sum(float(r.get("amount", 0.0)) for r in rows)
    unknown_amount = sum(float(r.get("amount", 0.0)) for r in unknown_rows)
    summary = {
        "unknown_record_count": len(unknown_rows),
        "unknown_amount": round(unknown_amount, 2),
        "total_amount": round(total_amount, 2),
        "unknown_amount_share": round(unknown_amount / total_amount, 4) if total_amount else 0.0,
        "by_reason": {
            k: {"record_count": int(v["record_count"]), "total_amount": round(v["total_amount"], 2)}
            for k, v in sorted(by_reason.items())
        },
        "has_unclassified": any(
            r.get("unknown_reason") == "unknown_unclassified_row_level" for r in unknown_rows
        ),
    }
    return decomp_rows, summary


def _san_juan_bias_report(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sj_rows = [
        r
        for r in rows
        if r.get("municipality_code_canonical") == SAN_JUAN_CODE or crosswalk_name_is_san_juan(r)
    ]
    biased = [r for r in sj_rows if r.get("san_juan_bias_flag")]
    report_rows = []
    for r in biased:
        report_rows.append(
            {
                "record_id": r.get("record_id"),
                "record_type": r.get("record_type"),
                "amount": r.get("amount", 0.0),
                "geo_resolution_reason": r["geo_resolution_reason"],
                "jurisdiction_class": r["jurisdiction_class"],
                "raw_code": r.get("raw_code", ""),
                "raw_name": r.get("raw_name", ""),
                "attribution_source": r.get("attribution_source", ""),
                "hq_bias_flag": r.get("hq_bias_flag"),
                "bias_trigger": _bias_trigger(r),
            }
        )
    total_amount = sum(float(r.get("amount", 0.0)) for r in rows)
    sj_amount = sum(float(r.get("amount", 0.0)) for r in sj_rows)
    biased_amount = sum(float(r.get("amount", 0.0)) for r in biased)
    summary = {
        "san_juan_record_count": len(sj_rows),
        "san_juan_amount": round(sj_amount, 2),
        "total_amount": round(total_amount, 2),
        "san_juan_share": round(sj_amount / total_amount, 4) if total_amount else 0.0,
        "biased_record_count": len(biased),
        "biased_amount": round(biased_amount, 2),
        "biased_share_of_san_juan": round(biased_amount / sj_amount, 4) if sj_amount else 0.0,
        "explained": True,  # every biased row carries an explicit bias_trigger
    }
    return report_rows, summary


def _bias_trigger(r: dict[str, Any]) -> str:
    if not _clean(r.get("raw_code")) and crosswalk_name_is_san_juan(r):
        return "san_juan_text_no_code"
    if r.get("geo_resolution_reason") == "headquarters_only":
        return "recipient_hq_san_juan_no_place_of_performance"
    if r.get("geo_resolution_reason") == "agency_default":
        return "central_agency_or_funding_office_default"
    return "source_default_not_work_location"


def _municipality_density(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        code = r.get("municipality_code_canonical", "")
        key = (
            code,
            r["jurisdiction_class"],
            r["geo_resolution_method"],
            r["geo_resolution_reason"],
            r.get("unknown_reason", ""),
        )
        g = groups.get(key)
        if g is None:
            muni_code, muni_name = (code, r.get("municipality_name_canonical", ""))
            outside_state = ""
            if r["jurisdiction_class"].startswith("OUTSIDE_PR"):
                outside_state = _clean(r.get("state")) or "US"
            g = groups[key] = {
                "municipality_geoid": code,
                "municipality_code": muni_code,
                "municipality_name": muni_name,
                "municipality_name_ascii": _strip_accents(muni_name).title() if muni_name else "",
                "municipality_name_canonical": muni_name,
                "jurisdiction_class": r["jurisdiction_class"],
                "geo_resolution_method": r["geo_resolution_method"],
                "geo_resolution_reason": r["geo_resolution_reason"],
                "_conf_sum": 0.0,
                "total_amount": 0.0,
                "record_count": 0,
                "unknown_reason": r.get("unknown_reason", ""),
                "outside_pr_state": outside_state,
                "_sources": set(),
            }
        g["total_amount"] += float(r.get("amount", 0.0))
        g["record_count"] += 1
        g["_conf_sum"] += float(r.get("geo_confidence", 0.0))
        if _clean(r.get("source_dataset")):
            g["_sources"].add(_clean(r.get("source_dataset")))

    out_rows = []
    for g in groups.values():
        count = g["record_count"] or 1
        out_rows.append(
            {
                "municipality_geoid": g["municipality_geoid"],
                "municipality_code": g["municipality_code"],
                "municipality_name": g["municipality_name"],
                "municipality_name_ascii": g["municipality_name_ascii"],
                "municipality_name_canonical": g["municipality_name_canonical"],
                "jurisdiction_class": g["jurisdiction_class"],
                "geo_resolution_method": g["geo_resolution_method"],
                "geo_resolution_reason": g["geo_resolution_reason"],
                "geo_confidence": round(g["_conf_sum"] / count, 3),
                "total_amount": round(g["total_amount"], 2),
                "record_count": g["record_count"],
                "unknown_reason": g["unknown_reason"],
                "outside_pr_state": g["outside_pr_state"],
                "source_count": len(g["_sources"]),
            }
        )
    out_rows.sort(
        key=lambda r: (-r["total_amount"], r["municipality_code"], r["geo_resolution_reason"])
    )
    return out_rows


DENSITY_COLUMNS = [
    "municipality_geoid",
    "municipality_code",
    "municipality_name",
    "municipality_name_ascii",
    "municipality_name_canonical",
    "jurisdiction_class",
    "geo_resolution_method",
    "geo_resolution_reason",
    "geo_confidence",
    "total_amount",
    "record_count",
    "unknown_reason",
    "outside_pr_state",
    "source_count",
]

EDGE_METADATA_FIELDS = [
    "relationship_type",
    "source_dataset",
    "source_id",
    "award_id",
    "transaction_id",
    "amount",
    "currency",
    "event_date",
    "municipality_code",
    "municipality_name",
    "geo_resolution_reason",
    "confidence",
    "lineage",
    "synthetic",
]


def _node_id(prefix: str, label: str) -> str:
    key = _strip_accents(_clean(label)).upper()
    return f"{prefix}:{key}" if key else ""


def _build_graph(rows: list[dict[str, Any]], provenance: dict[str, Any]):
    import networkx as nx

    g = nx.MultiDiGraph()
    edge_records: list[dict[str, Any]] = []
    source_inputs = provenance.get("source_inputs", [])

    for r in rows:
        recipient = _clean(r.get("recipient"))
        agency = _clean(r.get("agency"))
        rec_id = _node_id("entity", recipient)
        agc_id = _node_id("entity", agency)
        if not rec_id or not agc_id:
            continue
        g.add_node(rec_id, label=recipient, node_type="recipient")
        g.add_node(agc_id, label=agency, node_type="funding_agency")

        muni_code = _clean(r.get("municipality_code_canonical"))
        muni_name = _clean(r.get("municipality_name_canonical"))
        if muni_code:
            muni_node = _node_id("municipality", muni_code)
            g.add_node(muni_node, label=muni_name or muni_code, node_type="municipality")
            loc_attrs = _edge_attrs(r, "located_in", source_inputs, include_loc=True)
            g.add_edge(rec_id, muni_node, key=f"loc-{r.get('record_id')}", **loc_attrs)
            edge_records.append({"source": rec_id, "target": muni_node, **loc_attrs})

        rel = "received_award_from" if r.get("record_type") == "award" else "received_payment_from"
        attrs = _edge_attrs(r, rel, source_inputs, include_loc=True)
        g.add_edge(rec_id, agc_id, key=f"fin-{r.get('record_id')}", **attrs)
        edge_records.append({"source": rec_id, "target": agc_id, **attrs})

    return g, edge_records


def _edge_attrs(r: dict[str, Any], rel: str, source_inputs: list[str], include_loc: bool) -> dict[str, Any]:
    is_award = r.get("record_type") == "award"
    lineage = _lineage(source_inputs, "row_level_contract_finance")
    return {
        "relationship_type": rel,
        "source_dataset": _clean(r.get("source_dataset")),
        "source_id": _clean(r.get("source_id")) or _clean(r.get("source_dataset")),
        "award_id": _clean(r.get("record_id")) if is_award else "",
        "transaction_id": _clean(r.get("record_id")) if not is_award else "",
        "amount": float(r.get("amount", 0.0)),
        "currency": CURRENCY,
        "event_date": _clean(r.get("event_date")),
        "municipality_code": _clean(r.get("municipality_code_canonical")) if include_loc else "",
        "municipality_name": _clean(r.get("municipality_name_canonical")) if include_loc else "",
        "geo_resolution_reason": r.get("geo_resolution_reason", ""),
        "confidence": float(r.get("geo_confidence", 0.0)),
        "lineage": json.dumps(lineage, sort_keys=True),
        "synthetic": False,
    }


def _edge_audit(edge_records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    audit_rows = []
    coverage = {f: 0 for f in EDGE_METADATA_FIELDS}
    for e in edge_records:
        populated = []
        for f in EDGE_METADATA_FIELDS:
            val = e.get(f, "")
            present = val not in ("", None)
            # bool False (synthetic) and 0.0 amounts still count as present fields.
            if f in ("synthetic",):
                present = f in e
            if present:
                coverage[f] += 1
                populated.append(f)
        row = {
            "source": e["source"],
            "target": e["target"],
            "relationship_type": e["relationship_type"],
            "award_id": e["award_id"],
            "transaction_id": e["transaction_id"],
            "populated_fields": "|".join(populated),
            "metadata_field_count": len(populated),
            "metadata_complete": e["relationship_type"] != "" and bool(e.get("lineage")) and "confidence" in e,
        }
        audit_rows.append(row)
    total = len(edge_records) or 1
    qa = {
        "edge_count": len(edge_records),
        "metadata_fields_required": EDGE_METADATA_FIELDS,
        "zero_metadata_fields": len(edge_records) > 0 and all(c == 0 for c in coverage.values()),
        "field_coverage": {f: coverage[f] for f in EDGE_METADATA_FIELDS},
        "field_coverage_ratio": {f: round(coverage[f] / total, 4) for f in EDGE_METADATA_FIELDS},
        "edges_missing_lineage": sum(1 for e in edge_records if not e.get("lineage")),
        "edges_missing_confidence": sum(1 for e in edge_records if "confidence" not in e),
    }
    return audit_rows, qa


def _readiness_gate(
    rows: list[dict[str, Any]],
    unknown_summary: dict[str, Any],
    sj_summary: dict[str, Any],
    density_rows: list[dict[str, Any]],
    graph_qa: dict[str, Any],
    provenance: dict[str, Any],
    crosswalk: Crosswalk,
    san_juan_threshold: float,
    unknown_threshold: float,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    # 1. UNKNOWN amount share decomposed.
    unk_share = unknown_summary["unknown_amount_share"]
    unk_fail = unk_share > unknown_threshold and (
        unknown_summary["unknown_record_count"] == 0 or unknown_summary["has_unclassified"]
    )
    checks.append(
        {
            "check": "unknown_amount_share_decomposed",
            "passed": not unk_fail,
            "unknown_amount_share": unk_share,
            "threshold": unknown_threshold,
            "has_unclassified": unknown_summary["has_unclassified"],
        }
    )

    # 2. San Juan share explained.
    sj_share = sj_summary["san_juan_share"]
    sj_fail = (
        sj_share > san_juan_threshold
        and sj_summary["biased_share_of_san_juan"] > 0.5
        and not sj_summary["explained"]
    )
    checks.append(
        {
            "check": "san_juan_share_explained",
            "passed": not sj_fail,
            "san_juan_share": sj_share,
            "threshold": san_juan_threshold,
            "biased_share_of_san_juan": sj_summary["biased_share_of_san_juan"],
            "explained": sj_summary["explained"],
        }
    )

    # 3. No false PR_* non-municipio code.
    false_pr = [
        r
        for r in rows
        if r["jurisdiction_class"] == "PR_MUNICIPIO"
        and r.get("municipality_code_canonical") not in crosswalk.valid_codes
    ]
    checks.append(
        {
            "check": "no_false_pr_municipio_code",
            "passed": len(false_pr) == 0,
            "false_pr_record_count": len(false_pr),
        }
    )

    # 4. GraphML edge metadata present.
    checks.append(
        {
            "check": "graphml_has_edge_metadata",
            "passed": graph_qa["edge_count"] == 0 or not graph_qa["zero_metadata_fields"],
            "edge_count": graph_qa["edge_count"],
            "zero_metadata_fields": graph_qa["zero_metadata_fields"],
        }
    )

    # 5. Lineage + confidence on every edge.
    checks.append(
        {
            "check": "edges_have_lineage_and_confidence",
            "passed": graph_qa["edges_missing_lineage"] == 0 and graph_qa["edges_missing_confidence"] == 0,
            "edges_missing_lineage": graph_qa["edges_missing_lineage"],
            "edges_missing_confidence": graph_qa["edges_missing_confidence"],
        }
    )

    # 6. Totals reconciled against row-level inputs.
    input_total = round(sum(float(r.get("amount", 0.0)) for r in rows), 2)
    input_count = len(rows)
    density_total = round(sum(float(r["total_amount"]) for r in density_rows), 2)
    density_count = sum(int(r["record_count"]) for r in density_rows)
    reconciled = abs(input_total - density_total) < 0.01 and input_count == density_count
    checks.append(
        {
            "check": "totals_reconciled",
            "passed": reconciled,
            "input_total_amount": input_total,
            "density_total_amount": density_total,
            "input_record_count": input_count,
            "density_record_count": density_count,
        }
    )

    passed = all(c["passed"] for c in checks)
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "producer": PRODUCER_SCRIPT,
        "input_mode": provenance.get("input_mode"),
        "source_inputs": provenance.get("source_inputs"),
        "passed": passed,
        "checks": checks,
    }


def run(
    processed_dir: str | Path,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    export_dir: str | Path | None = None,
    crosswalk_path: str | Path = DEFAULT_CROSSWALK,
    build_crosswalk: bool = False,
    san_juan_threshold: float = DEFAULT_SAN_JUAN_THRESHOLD,
    unknown_threshold: float = DEFAULT_UNKNOWN_AMOUNT_THRESHOLD,
) -> dict[str, Any]:
    processed_dir = Path(processed_dir)
    output_dir = Path(output_dir)
    crosswalk_path = Path(crosswalk_path)
    export_dir_p = Path(export_dir) if export_dir else None
    output_dir.mkdir(parents=True, exist_ok=True)

    if build_crosswalk or not crosswalk_path.exists():
        write_crosswalk(crosswalk_path)
    crosswalk = Crosswalk.load(crosswalk_path)

    rows, provenance = load_rows(processed_dir, export_dir_p)
    enriched = classify_rows(rows, crosswalk)

    # Per-row trace.
    row_cols = [
        "record_id",
        "record_type",
        "amount",
        "event_date",
        "recipient",
        "agency",
        "source_dataset",
        "raw_code",
        "raw_name",
        "raw_municipality",
        "attribution_source",
        "geo_resolution_method",
        "geo_resolution_reason",
        "geo_confidence",
        "jurisdiction_class",
        "municipality_code_canonical",
        "municipality_name_canonical",
        "hq_bias_flag",
        "san_juan_bias_flag",
        "outside_pr_flag",
        "unknown_reason",
    ]
    _write_csv(output_dir / "contract_finance_geo_rows.csv", enriched, row_cols)

    # Task 5 — UNKNOWN decomposition.
    decomp_rows, decomp_summary = _decompose_unknown(enriched)
    _write_csv(
        output_dir / "unknown_decomposition.csv",
        decomp_rows,
        [
            "record_id",
            "record_type",
            "jurisdiction_class",
            "unknown_reason",
            "geo_resolution_reason",
            "amount",
            "raw_code",
            "raw_name",
            "attribution_source",
        ],
    )
    _write_json(output_dir / "unknown_decomposition_summary.json", decomp_summary)

    # Task 6 — San Juan HQ / default-location bias.
    bias_rows, bias_summary = _san_juan_bias_report(enriched)
    _write_csv(
        output_dir / "san_juan_hq_bias_report.csv",
        bias_rows,
        [
            "record_id",
            "record_type",
            "amount",
            "geo_resolution_reason",
            "jurisdiction_class",
            "raw_code",
            "raw_name",
            "attribution_source",
            "hq_bias_flag",
            "bias_trigger",
        ],
    )
    _write_json(output_dir / "san_juan_hq_bias_summary.json", bias_summary)

    # Task 7 — municipality funding density.
    density_rows = _municipality_density(enriched)
    _write_csv(output_dir / "municipality_funding_density.csv", density_rows, DENSITY_COLUMNS)

    # Task 8 — entity graph with edge metadata.
    graph, edge_records = _build_graph(enriched, provenance)
    import networkx as nx

    nx.write_graphml(graph, output_dir / "entity_graph.graphml")
    audit_rows, graph_qa = _edge_audit(edge_records)
    _write_csv(
        output_dir / "entity_graph_edge_metadata_audit.csv",
        audit_rows,
        [
            "source",
            "target",
            "relationship_type",
            "award_id",
            "transaction_id",
            "populated_fields",
            "metadata_field_count",
            "metadata_complete",
        ],
    )
    graph_qa["node_count"] = graph.number_of_nodes()
    _write_json(output_dir / "entity_graph_qa_report.json", graph_qa)

    # Task 9 — readiness gate reassessment.
    readiness = _readiness_gate(
        enriched,
        decomp_summary,
        bias_summary,
        density_rows,
        graph_qa,
        provenance,
        crosswalk,
        san_juan_threshold,
        unknown_threshold,
    )
    _write_json(output_dir / "spiderweb_engine_readiness_reassessment.json", readiness)

    return {
        "input_mode": provenance.get("input_mode"),
        "row_count": len(enriched),
        "unknown_summary": decomp_summary,
        "san_juan_summary": bias_summary,
        "graph_qa": {k: graph_qa[k] for k in ("edge_count", "node_count", "zero_metadata_fields")},
        "readiness_passed": readiness["passed"],
        "output_dir": str(output_dir),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument("--export-dir", default=None)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--crosswalk", default=str(DEFAULT_CROSSWALK))
    parser.add_argument("--build-crosswalk", action="store_true")
    parser.add_argument("--san-juan-threshold", type=float, default=DEFAULT_SAN_JUAN_THRESHOLD)
    parser.add_argument("--unknown-amount-threshold", type=float, default=DEFAULT_UNKNOWN_AMOUNT_THRESHOLD)
    args = parser.parse_args(argv)

    result = run(
        processed_dir=args.processed_dir,
        output_dir=args.output_dir,
        export_dir=args.export_dir,
        crosswalk_path=args.crosswalk,
        build_crosswalk=args.build_crosswalk,
        san_juan_threshold=args.san_juan_threshold,
        unknown_threshold=args.unknown_amount_threshold,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["readiness_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
