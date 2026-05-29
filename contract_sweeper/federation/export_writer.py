"""Write a Contract-Sweeper federation *evidence-envelope* export package.

.. note::
   This module is the **evidence-envelope track** (``schema_version "0.1"``,
   records shaped as ``record_id``/``payload``/``entities[]``/``geo``). It is
   **NOT** the on-wire financial export contract consumed by spiderweb-pr's
   ``contract_finance`` layer. That live contract is the flat v1.2.0 stream
   shape produced by ``scripts/build_export_package.py``, defined by
   ``schemas/contract_sweeper_*.schema.json``, and enforced by
   ``scripts/validate_export.py``. Do not confuse the two: editing this file
   does not change what the federation handoff ships. See
   ``docs/export_contract.md``.

A package is a directory containing one ``<stream>.jsonl`` file per record
stream plus a ``manifest.json`` sidecar. Each JSONL line is one evidence
envelope. The builder helpers reuse the repo's existing entity-name
normalization and link-confidence scoring so the export stays consistent with
the rest of the pipeline.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Union

from contract_sweeper.runtime.linkage_confidence import LinkSignals, score_subaward_link
from contract_sweeper.runtime.name_normalization import normalize_name

from .envelope import EvidenceEnvelope, entity_ref
from .namespace import PREFIX, PRODUCER, namespaced_id

SCHEMA_VERSION = "0.1"

# stream filename stem -> envelope record_type
STREAM_RECORD_TYPES = {
    "funding_awards": "funding_award",
    "transactions": "transaction",
    "entities": "entity",
    "relationships": "relationship",
    "sources": "source",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coerce(record: Union[EvidenceEnvelope, Dict[str, Any]]) -> Dict[str, Any]:
    if isinstance(record, EvidenceEnvelope):
        return record.to_dict()
    if isinstance(record, dict):
        return record
    raise TypeError(f"record must be EvidenceEnvelope or dict, got {type(record)!r}")


def write_stream(path: Union[str, Path], records: Iterable) -> int:
    """Write records as one JSON object per line. Returns the count."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(_coerce(record), ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def write_package(
    out_dir: Union[str, Path],
    streams: Mapping[str, Iterable],
    *,
    synthetic: bool = False,
    producer: str = PRODUCER,
) -> Dict[str, Any]:
    """Write every stream + a manifest.json. Returns the manifest dict."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: List[Dict[str, Any]] = []
    for name, records in streams.items():
        filename = f"{name}.jsonl"
        count = write_stream(out / filename, records)
        files.append(
            {
                "filename": filename,
                "record_type": STREAM_RECORD_TYPES.get(name, name),
                "record_count": count,
                "sha256": _sha256(out / filename),
            }
        )
    manifest = {
        "producer": producer,
        "prefix": PREFIX,
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "synthetic": bool(synthetic),
        "files": files,
    }
    (out / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


# --------------------------------------------------------------------------
# Envelope builders (reuse existing normalization + confidence scoring)
# --------------------------------------------------------------------------


def build_entity(
    raw_entity_id: str,
    name: str,
    *,
    source_id: str,
    synthetic: bool = False,
    lineage: Optional[List[Any]] = None,
) -> EvidenceEnvelope:
    nid = namespaced_id(raw_entity_id)
    ref = entity_ref(nid, name, normalize_name(name))
    return EvidenceEnvelope(
        producer=PRODUCER,
        record_type="entity",
        record_id=nid,
        source_id=namespaced_id(source_id),
        entities=[ref],
        confidence={"score": 1.0, "method": "producer_contract"},
        lineage=list(lineage or [{"stage": "entity_resolution"}]),
        payload={},
        synthetic=synthetic,
    )


def build_award(
    raw_award_id: str,
    *,
    source_id: str,
    amount: float,
    currency: str,
    award_date: Optional[str],
    entities: List[Dict[str, Any]],
    signals: Optional[LinkSignals] = None,
    synthetic: bool = False,
    lineage: Optional[List[Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> EvidenceEnvelope:
    if signals is not None:
        score = score_subaward_link(signals)
        method = "linkage_confidence"
    else:
        score = 0.91
        method = "producer_contract"
    body = dict(payload or {})
    body.update({"amount": amount, "currency": currency})
    return EvidenceEnvelope(
        producer=PRODUCER,
        record_type="funding_award",
        record_id=namespaced_id(raw_award_id),
        source_id=namespaced_id(source_id),
        timestamp=award_date,
        entities=list(entities),
        confidence={"score": score, "method": method},
        lineage=list(lineage or [{"stage": "award_ingest"}]),
        payload=body,
        synthetic=synthetic,
    )
