"""Map Contract-Sweeper canonical master tables into export streams.

Reads the canonical master tables produced by the pipeline (see
``registries/schema_registry.json``) from a processed directory and writes the
five pre-shaped JSONL stream files that ``scripts/build_export_package.py``
packages:

    entities.jsonl  sources.jsonl  funding_awards.jsonl
    transactions.jsonl  relationships.jsonl

The mapper is **fail-closed**: any row that would produce a dangling foreign
key, a negative/non-finite amount, a missing currency, or an unparseable date
is excluded and tallied in the returned report rather than emitted. The
resulting streams are designed to pass ``validate_export.validate_package(...,
mode="production")``.

Inputs (canonical table -> physical file under ``--processed-dir``):

* ``entities_resolved.csv``      -> entities
* ``contracts_master.csv``       -> funding_awards
* ``financial_flows_master.csv`` -> transactions
* ``entity_edges.csv``           -> relationships

Sources are derived from ``registries/source_registry.json`` enriched with the
source identifiers actually referenced by the data.

This module does not modify or re-run any pipeline stage; it only reads
already-produced masters.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contract_sweeper.runtime.name_normalization import normalize_name
from scripts.build_export_package import _deterministic_id

DEFAULT_PROCESSED_DIR = REPO_ROOT / "data" / "staging" / "processed"
SOURCE_REGISTRY_PATH = REPO_ROOT / "registries" / "source_registry.json"

CURRENCY = "USD"
DEFAULT_JURISDICTION = "US"
DEFAULT_CONFIDENCE = 0.5  # used only when an input confidence column is absent

# Canonical input filenames.
ENTITIES_FILE = "entities_resolved.csv"
CONTRACTS_FILE = "contracts_master.csv"
FLOWS_FILE = "financial_flows_master.csv"
EDGES_FILE = "entity_edges.csv"

# A derived provenance source for rows the pipeline synthesizes (resolved
# entities, synthesized funding agencies).
DERIVED_SOURCE_REF = "contract_sweeper_resolution"

# Entity rows that are aggregates / sentinels, not real entities.
SENTINEL_NORMALIZED_NAMES = {"MULTIPLE RECIPIENTS", "UNKNOWN", ""}
SENTINEL_ENTITY_TYPES = {"aggregate"}


@dataclass
class StreamReport:
    """Per-stream accounting of emitted vs skipped rows."""

    emitted: int = 0
    skipped: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped[reason] = self.skipped.get(reason, 0) + 1


@dataclass
class BuildReport:
    streams: dict[str, StreamReport] = field(default_factory=dict)

    def for_stream(self, name: str) -> StreamReport:
        return self.streams.setdefault(name, StreamReport())

    def as_dict(self) -> dict[str, Any]:
        return {
            name: {"emitted": r.emitted, "skipped": r.skipped}
            for name, r in self.streams.items()
        }


# --------------------------------------------------------------------------- #
# Parsing helpers (tolerant, fail-closed)                                      #
# --------------------------------------------------------------------------- #

def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _clean(value: str | None) -> str:
    return (value or "").strip()


def _parse_amount(raw: str | None) -> float | None:
    s = _clean(raw)
    if not s:
        return None
    s = s.replace("$", "").replace(",", "")
    try:
        amount = float(s)
    except ValueError:
        return None
    if not math.isfinite(amount):
        return None
    return amount


def _parse_fiscal_year(raw: str | None) -> int | None:
    s = _clean(raw)
    if not s:
        return None
    try:
        return int(float(s))
    except ValueError:
        return None


def _parse_date(raw: str | None) -> str | None:
    """Return a YYYY-MM-DD date string, or None if unparseable."""
    s = _clean(raw)
    if not s:
        return None
    # Take the date portion if a full timestamp is supplied.
    head = s.split("T", 1)[0].split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(head, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_confidence(raw: str | None) -> float:
    s = _clean(raw)
    if not s:
        return DEFAULT_CONFIDENCE
    try:
        value = float(s)
    except ValueError:
        return DEFAULT_CONFIDENCE
    if not math.isfinite(value):
        return DEFAULT_CONFIDENCE
    return min(1.0, max(0.0, value))


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Sources                                                                      #
# --------------------------------------------------------------------------- #

def _load_source_registry() -> dict[str, dict[str, Any]]:
    if not SOURCE_REGISTRY_PATH.exists():
        return {}
    data = json.loads(SOURCE_REGISTRY_PATH.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for entry in data.get("sources", []) or []:
        sid = entry.get("source_id")
        if sid:
            out[sid] = entry
    return out


def _build_source_row(source_ref: str, registry: dict[str, dict[str, Any]], ts: str) -> dict[str, Any]:
    reg = registry.get(source_ref)
    if reg is not None:
        source_type = reg.get("family", "external")
        source_name = reg.get("notes", "").splitlines()[0] if reg.get("notes") else source_ref
        source_url = reg.get("endpoint_url")
    elif source_ref == DERIVED_SOURCE_REF:
        source_type = "derived"
        source_name = "Contract-Sweeper entity resolution"
        source_url = None
    else:
        source_type = "external"
        source_name = source_ref.replace("_", " ").title()
        source_url = None

    source_id = _deterministic_id(
        "src",
        {"source_type": source_type, "source_name": source_name, "source_ref": source_ref},
    )
    row: dict[str, Any] = {
        "source_id": source_id,
        "source_type": source_type,
        "source_name": source_name or source_ref,
        "source_ref": source_ref,
        "confidence": 1.0,
        "lineage": {
            "producer_script": "scripts/write_source_manifests.py",
            "producer_phase": "R0_SOURCE_REGISTRY",
            "source_inputs": ["registries/source_registry.json"],
            "extraction_method": "source_registry",
        },
        "synthetic": False,
        "created_at": ts,
        "extracted_at": ts,
    }
    if source_url:
        row["source_url"] = source_url
    return row


# --------------------------------------------------------------------------- #
# Crosswalk                                                                    #
# --------------------------------------------------------------------------- #

class Crosswalk:
    """Resolves repo entity keys (uei, internal id, normalized name) to export ent_ids."""

    def __init__(self) -> None:
        self._by_key: dict[str, str] = {}

    def register(self, ent_id: str, *keys: str) -> None:
        for key in keys:
            k = _clean(key)
            if k:
                self._by_key.setdefault(k.upper(), ent_id)

    def resolve(self, *keys: str) -> str | None:
        for key in keys:
            k = _clean(key)
            if k:
                hit = self._by_key.get(k.upper())
                if hit:
                    return hit
        return None


# --------------------------------------------------------------------------- #
# Entities (resolved + synthesized funding agencies)                           #
# --------------------------------------------------------------------------- #

def _entity_id_for(normalized_name: str, entity_type: str, jurisdiction: str) -> str:
    return _deterministic_id(
        "ent",
        {
            "normalized_name": normalized_name,
            "entity_type": entity_type,
            "jurisdiction": jurisdiction,
        },
    )


def _build_entities(
    resolved_rows: list[dict[str, str]],
    agency_names: Iterable[str],
    derived_source_id: str,
    crosswalk: Crosswalk,
    ts: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    rep = report.for_stream("entities")
    out: dict[str, dict[str, Any]] = {}

    for row in resolved_rows:
        norm = _clean(row.get("normalized_name")) or normalize_name(row.get("entity_name"))
        etype = _clean(row.get("entity_type")) or "recipient"
        if norm.upper() in SENTINEL_NORMALIZED_NAMES or etype in SENTINEL_ENTITY_TYPES:
            rep.skip("sentinel_or_aggregate")
            continue
        ent_id = _entity_id_for(norm, etype, DEFAULT_JURISDICTION)
        source_files = [s for s in _clean(row.get("source_files")).split(";") if s]
        out[ent_id] = {
            "entity_id": ent_id,
            "source_id": derived_source_id,
            "name": _clean(row.get("entity_name")) or norm,
            "normalized_name": norm,
            "entity_type": etype,
            "jurisdiction": DEFAULT_JURISDICTION,
            "confidence": _parse_confidence(row.get("match_confidence")),
            "lineage": {
                "producer_script": "scripts/entity_resolution.py",
                "producer_phase": "R3_ENTITY_RESOLUTION",
                "source_inputs": source_files or [ENTITIES_FILE],
                "extraction_method": _clean(row.get("resolution_method")) or "entity_resolution",
            },
            "synthetic": False,
            "created_at": ts,
            "extracted_at": ts,
        }
        crosswalk.register(ent_id, row.get("entity_uei"), row.get("entity_id"), norm, row.get("entity_name"))

    # Synthesize funding-agency entities referenced by awards/flows.
    for raw_agency in agency_names:
        agency = _clean(raw_agency)
        if not agency:
            continue
        norm = normalize_name(agency)
        if norm.upper() in SENTINEL_NORMALIZED_NAMES:
            continue
        if crosswalk.resolve(norm, agency) is not None:
            continue
        ent_id = _entity_id_for(norm, "funding_agency", DEFAULT_JURISDICTION)
        if ent_id not in out:
            out[ent_id] = {
                "entity_id": ent_id,
                "source_id": derived_source_id,
                "name": agency,
                "normalized_name": norm,
                "entity_type": "funding_agency",
                "jurisdiction": DEFAULT_JURISDICTION,
                "confidence": 1.0,
                "lineage": {
                    "producer_script": "scripts/build_export_streams.py",
                    "producer_phase": "R8_EXPORT_AGENCY_SYNTHESIS",
                    "source_inputs": [CONTRACTS_FILE, FLOWS_FILE],
                    "extraction_method": "agency_synthesis",
                },
                "synthetic": False,
                "created_at": ts,
                "extracted_at": ts,
            }
        crosswalk.register(ent_id, norm, agency)

    rep.emitted = len(out)
    return list(out.values())


# --------------------------------------------------------------------------- #
# Awards / transactions / relationships                                        #
# --------------------------------------------------------------------------- #

def _build_awards(
    rows: list[dict[str, str]],
    crosswalk: Crosswalk,
    source_id_for: Callable[[str], str],
    ts: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    rep = report.for_stream("funding_awards")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        amount = _parse_amount(row.get("obligation_amount"))
        if amount is None or amount < 0:
            rep.skip("invalid_or_negative_amount")
            continue
        award_date = _parse_date(row.get("award_date"))
        if award_date is None:
            rep.skip("bad_date")
            continue
        fiscal_year = _parse_fiscal_year(row.get("fiscal_year"))
        if fiscal_year is None:
            rep.skip("bad_fiscal_year")
            continue
        recipient = crosswalk.resolve(row.get("recipient_uei"), row.get("normalized_name"), row.get("recipient_name"))
        if recipient is None:
            rep.skip("unresolved_recipient")
            continue
        agency = crosswalk.resolve(normalize_name(row.get("awarding_agency")), row.get("awarding_agency"))
        if agency is None:
            rep.skip("unresolved_agency")
            continue
        source_id = source_id_for(_clean(row.get("source_system")))
        award_id = _deterministic_id(
            "awd",
            {
                "source_id": source_id,
                "recipient_entity_id": recipient,
                "funding_agency_entity_id": agency,
                "award_date": award_date,
                "amount": amount,
                "currency": CURRENCY,
                "fiscal_year": fiscal_year,
            },
        )
        out[award_id] = {
            "award_id": award_id,
            "source_id": source_id,
            "recipient_entity_id": recipient,
            "funding_agency_entity_id": agency,
            "amount": amount,
            "currency": CURRENCY,
            "fiscal_year": fiscal_year,
            "award_type": _clean(row.get("funding_source")) or "contract",
            "award_date": award_date,
            "confidence": _parse_confidence(row.get("link_confidence")),
            "lineage": {
                "producer_script": "scripts/deduplicate_master.py",
                "producer_phase": "R4_CONTRACTS_MASTER",
                "source_inputs": [CONTRACTS_FILE],
                "extraction_method": "canonical_contracts_master",
            },
            "synthetic": False,
            "created_at": ts,
            "extracted_at": ts,
        }
    rep.emitted = len(out)
    return list(out.values())


def _build_transactions(
    rows: list[dict[str, str]],
    crosswalk: Crosswalk,
    source_id_for: Callable[[str], str],
    ts: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    rep = report.for_stream("transactions")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        amount = _parse_amount(row.get("amount"))
        if amount is None or amount < 0:
            rep.skip("invalid_or_negative_amount")
            continue
        txn_date = _parse_date(row.get("flow_date"))
        if txn_date is None:
            rep.skip("bad_date")
            continue
        payee = crosswalk.resolve(row.get("recipient_entity_id"))
        if payee is None:
            rep.skip("unresolved_payee")
            continue
        payer = crosswalk.resolve(normalize_name(row.get("funding_source")), row.get("funding_source"))
        if payer is None:
            rep.skip("unresolved_payer")
            continue
        source_id = source_id_for(_clean(row.get("source_system")))
        txn_id = _deterministic_id(
            "txn",
            {
                "source_id": source_id,
                "payer_entity_id": payer,
                "payee_entity_id": payee,
                "transaction_date": txn_date,
                "amount": amount,
                "currency": CURRENCY,
                "transaction_type": "disbursement",
            },
        )
        out[txn_id] = {
            "transaction_id": txn_id,
            "source_id": source_id,
            "payer_entity_id": payer,
            "payee_entity_id": payee,
            "amount": amount,
            "currency": CURRENCY,
            "transaction_date": txn_date,
            "transaction_type": "disbursement",
            "confidence": _parse_confidence(row.get("link_confidence")),
            "lineage": {
                "producer_script": "scripts/build_financial_flows_master.py",
                "producer_phase": "R6_FINANCIAL_FLOWS",
                "source_inputs": [FLOWS_FILE],
                "extraction_method": "canonical_financial_flows_master",
            },
            "synthetic": False,
            "created_at": ts,
            "extracted_at": ts,
        }
    rep.emitted = len(out)
    return list(out.values())


def _build_relationships(
    rows: list[dict[str, str]],
    crosswalk: Crosswalk,
    source_id_for: Callable[[str], str],
    ts: str,
    report: BuildReport,
) -> list[dict[str, Any]]:
    rep = report.for_stream("relationships")
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        src = crosswalk.resolve(normalize_name(row.get("source")), row.get("source"))
        tgt = crosswalk.resolve(normalize_name(row.get("target")), row.get("target"))
        if src is None or tgt is None:
            rep.skip("unresolved_endpoint")
            continue
        rel_type = _clean(row.get("edge_type")) or "related_to"
        evidence_source_id = source_id_for(_clean(row.get("source_dataset")))
        rel_id = _deterministic_id(
            "rel",
            {
                "source_entity_id": src,
                "target_entity_id": tgt,
                "relationship_type": rel_type,
                "evidence_source_id": evidence_source_id,
            },
        )
        out[rel_id] = {
            "relationship_id": rel_id,
            "source_id": evidence_source_id,
            "source_entity_id": src,
            "target_entity_id": tgt,
            "relationship_type": rel_type,
            "evidence_source_id": evidence_source_id,
            "confidence": _parse_confidence(row.get("confidence")),
            "lineage": {
                "producer_script": "scripts/influence_graph_builder.py",
                "producer_phase": "R7_ENTITY_EDGES",
                "source_inputs": [EDGES_FILE],
                "extraction_method": "canonical_entity_edges",
            },
            "synthetic": False,
            "created_at": ts,
            "extracted_at": ts,
        }
    rep.emitted = len(out)
    return list(out.values())


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #

def _id_field(stream: str) -> str:
    return {
        "entities": "entity_id",
        "sources": "source_id",
        "funding_awards": "award_id",
        "transactions": "transaction_id",
        "relationships": "relationship_id",
    }[stream]


def _write_jsonl(path: Path, rows: list[dict[str, Any]], id_field: str) -> None:
    rows_sorted = sorted(rows, key=lambda r: r[id_field])
    with path.open("w", encoding="utf-8") as f:
        for row in rows_sorted:
            f.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")


def build_streams(
    processed_dir: str | Path,
    staging_dir: str | Path,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Read canonical masters from ``processed_dir`` and write 5 JSONL streams.

    Returns a report dict with per-stream emitted/skipped counts.
    """
    processed = Path(processed_dir)
    staging = Path(staging_dir)
    staging.mkdir(parents=True, exist_ok=True)
    ts = generated_at or _utc_now_iso()
    report = BuildReport()

    resolved_rows = _read_csv(processed / ENTITIES_FILE)
    contract_rows = _read_csv(processed / CONTRACTS_FILE)
    flow_rows = _read_csv(processed / FLOWS_FILE)
    edge_rows = _read_csv(processed / EDGES_FILE)

    # Sources: union of the derived source + source identifiers referenced by data.
    registry = _load_source_registry()
    refs: set[str] = {DERIVED_SOURCE_REF}
    for r in contract_rows:
        if _clean(r.get("source_system")):
            refs.add(_clean(r.get("source_system")))
    for r in flow_rows:
        if _clean(r.get("source_system")):
            refs.add(_clean(r.get("source_system")))
    for r in edge_rows:
        if _clean(r.get("source_dataset")):
            refs.add(_clean(r.get("source_dataset")))

    source_rows: dict[str, dict[str, Any]] = {}
    ref_to_id: dict[str, str] = {}
    for ref in sorted(refs):
        row = _build_source_row(ref, registry, ts)
        source_rows[row["source_id"]] = row
        ref_to_id[ref] = row["source_id"]

    derived_source_id = ref_to_id[DERIVED_SOURCE_REF]

    def source_id_for(ref: str) -> str:
        ref = ref or DERIVED_SOURCE_REF
        if ref not in ref_to_id:
            row = _build_source_row(ref, registry, ts)
            source_rows[row["source_id"]] = row
            ref_to_id[ref] = row["source_id"]
        return ref_to_id[ref]

    report.for_stream("sources").emitted = len(source_rows)

    # Entities (resolved + synthesized agencies referenced by awards/flows).
    crosswalk = Crosswalk()
    agency_names = [r.get("awarding_agency", "") for r in contract_rows] + [
        r.get("funding_source", "") for r in flow_rows
    ]
    entity_rows = _build_entities(resolved_rows, agency_names, derived_source_id, crosswalk, ts, report)

    award_rows = _build_awards(contract_rows, crosswalk, source_id_for, ts, report)
    txn_rows = _build_transactions(flow_rows, crosswalk, source_id_for, ts, report)
    rel_rows = _build_relationships(edge_rows, crosswalk, source_id_for, ts, report)

    # source_rows may have grown via source_id_for(); refresh count.
    report.for_stream("sources").emitted = len(source_rows)

    streams = {
        "entities": entity_rows,
        "sources": list(source_rows.values()),
        "funding_awards": award_rows,
        "transactions": txn_rows,
        "relationships": rel_rows,
    }
    filenames = {
        "entities": "entities.jsonl",
        "sources": "sources.jsonl",
        "funding_awards": "funding_awards.jsonl",
        "transactions": "transactions.jsonl",
        "relationships": "relationships.jsonl",
    }
    for stream, rows in streams.items():
        _write_jsonl(staging / filenames[stream], rows, _id_field(stream))

    return report.as_dict()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Map canonical master tables into export JSONL streams.",
    )
    parser.add_argument("--processed-dir", default=str(DEFAULT_PROCESSED_DIR))
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument(
        "--generated-at",
        default=None,
        help="ISO-8601 tz-aware timestamp for created_at/extracted_at (default: now UTC).",
    )
    args = parser.parse_args(argv)

    report = build_streams(args.processed_dir, args.staging_dir, generated_at=args.generated_at)
    print(json.dumps({"export_streams_report": report}, indent=2, sort_keys=True))
    total_emitted = sum(s["emitted"] for s in report.values())
    print(f"[OK] wrote 5 streams to {args.staging_dir} ({total_emitted} total rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
