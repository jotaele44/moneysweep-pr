"""Consume Centinelas intake drops → MoneySweep pre-official located-finance candidates.

Centinelas (``centinelas-pr``) classifies public-interest items and drops JSON
payloads into this repo's ``intake/`` folder, routing ``FINANCIAL``/``POLITICAL``
signals to MoneySweep (the money anchor). This module is the MoneySweep-side
consumer of that drop: it reads the payloads, keeps the finance-relevant ones,
resolves each to a Puerto Rico municipality using the **existing** deterministic
geo attribution (:mod:`moneysweep.runtime.geo_attribution`), and emits
**pre-official located-finance candidate** rows in the export-stream shape that
``scripts/run_contract_finance_geo_reasoning.py`` already ingests
(``funding_awards.jsonl`` / ``transactions.jsonl`` with a ``location`` block).

These candidates are pre-officialization intelligence: they carry
``signal_stage="pre_official"`` and ``synthetic=false`` and are attributed to
``source_id="centinelas-pr"`` with full lineage, so downstream consumers can
distinguish them from officialized money while still placing them on the map.

Return shape mirrors :mod:`moneysweep.runtime.dropzone_ingest`:
``{"awards", "flows", "count", "status"}`` with ``status`` in
``NO_FILES | EMPTY | OK`` (``EMPTY`` = files present but none finance-relevant).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from moneysweep.runtime.geo_attribution import (
    _load_reference,
    _normalize_pr_name,
    attribute_geo,
)

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Centinelas domain labels that anchor to MoneySweep.
FINANCE_LABELS = {"FINANCIAL", "POLITICAL"}

SOURCE_ID = "centinelas-pr"
PRODUCER_SCRIPT = "moneysweep/runtime/centinelas_intake.py"
SIGNAL_STAGE = "pre_official"
CURRENCY = "USD"
_ATTRIBUTION_SOURCE = "centinelas_signal"


def default_intake_dir(root: Path | str = REPO_ROOT) -> Path:
    """Return the repo's Centinelas drop folder (``<root>/intake``)."""
    return Path(root) / "intake"


def load_drops(intake_dir: Path | str) -> list[tuple[Path, dict[str, Any]]]:
    """Read every ``*.json`` drop under ``intake_dir``. Malformed files are skipped."""
    intake_dir = Path(intake_dir)
    if not intake_dir.exists():
        return []
    out: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(intake_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping unreadable Centinelas drop %s: %s", path.name, exc)
            continue
        if isinstance(payload, dict):
            out.append((path, payload))
    return out


def is_finance_relevant(payload: dict[str, Any]) -> bool:
    """True when the drop carries a MoneySweep-anchored (FINANCIAL/POLITICAL) label."""
    labels = {str(x).upper() for x in (payload.get("labels") or [])}
    return bool(labels & FINANCE_LABELS)


def _first_str(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        for item in value:
            s = str(item).strip()
            if s:
                return s
        return ""
    return str(value).strip() if value is not None else ""


def _amount(payload: dict[str, Any]) -> float:
    raw = payload.get("estimated_value")
    if raw is None:
        return 0.0
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return value if value == value and value not in (float("inf"), float("-inf")) else 0.0


def _event_date(payload: dict[str, Any]) -> str:
    for key in ("published_at", "captured_at"):
        raw = _first_str(payload.get(key))
        if raw:
            return raw.split("T", 1)[0]
    return datetime.now(timezone.utc).date().isoformat()


def _extract_municipality_from_text(payload: dict[str, Any], root: Path | str) -> str:
    """Best-effort municipality name from title/body when the drop has no explicit one.

    Reuses the canonical PR municipality reference (accent-normalized aliases)
    that geo attribution already loads, matching whole normalized aliases against
    the normalized text. Conservative: prefers the longest matching alias and
    ignores very short (<4 char) aliases to avoid spurious token hits.
    """
    text = _normalize_pr_name(f"{payload.get('title', '')} {payload.get('body_text', '')}")
    if not text:
        return ""
    padded = f" {text} "
    by_alias = _load_reference(str(root))["by_alias"]
    best_name = ""
    best_len = 0
    for alias, record in by_alias.items():
        if len(alias) < 4:
            continue
        if f" {alias} " in padded and len(alias) > best_len:
            best_name = record["geo_municipality_name"]
            best_len = len(alias)
    return best_name


def _municipality_hint(payload: dict[str, Any], root: Path | str) -> str:
    """Municipality name for geo resolution: explicit enrichment first, then text."""
    explicit = _first_str(payload.get("municipalities"))
    if explicit:
        return explicit
    return _extract_municipality_from_text(payload, root)


def build_candidates(
    payloads: list[dict[str, Any]],
    *,
    root: Path | str = REPO_ROOT,
) -> list[dict[str, Any]]:
    """Turn finance-relevant drops into located pre-official funding-award candidates.

    Location is resolved with the deterministic :func:`attribute_geo` (same engine
    the rest of MoneySweep uses), so the candidate is genuinely *located* at intake
    time. Rows are export-stream shaped (an implicit ``funding_award``), carrying a
    ``location`` block that ``run_contract_finance_geo_reasoning.py`` consumes.
    """
    if not payloads:
        return []

    frame_rows: list[dict[str, Any]] = []
    for payload in payloads:
        frame_rows.append(
            {
                "item_id": _first_str(payload.get("item_id")) or _first_str(payload.get("signal_id")),
                "municipality": _municipality_hint(payload, root),
                "amount": _amount(payload),
                "event_date": _event_date(payload),
                "recipient": _first_str(payload.get("recipients")),
                "agency": _first_str(payload.get("agencies")),
                "source_url": _first_str(payload.get("source_url")),
                "evidence_tier": _first_str(payload.get("evidence_tier")) or "T3",
                "signal_stage": _first_str(payload.get("signal_stage")) or SIGNAL_STAGE,
                "beat": _first_str(payload.get("beat")),
            }
        )

    located = attribute_geo(pd.DataFrame(frame_rows), source_id=SOURCE_ID, root=Path(root))

    candidates: list[dict[str, Any]] = []
    for row in located.to_dict(orient="records"):
        item_id = str(row.get("item_id") or "")
        code = str(row.get("geo_municipality_code") or "")
        name = str(row.get("geo_municipality_name") or "")
        conf = str(row.get("geo_attribution_confidence") or "unknown")
        agency = str(row.get("agency") or "")
        # The awardee (who won) is distinct from the awarding agency (the funder).
        # Fall back to the agency only when no recipient was extracted, preserving
        # prior behavior for non-contractor finance signals.
        recipient = str(row.get("recipient") or "") or agency
        candidates.append(
            {
                "award_id": f"CS-CENT-{item_id}" if item_id else "CS-CENT-UNKNOWN",
                "centinelas_item_id": item_id,
                "amount": float(row.get("amount") or 0.0),
                "currency": CURRENCY,
                "award_date": str(row.get("event_date") or ""),
                "recipient_entity_id": recipient,
                "funding_agency_entity_id": agency,
                "source_id": SOURCE_ID,
                "signal_stage": str(row.get("signal_stage") or SIGNAL_STAGE),
                "beat": str(row.get("beat") or ""),
                "evidence_tier": str(row.get("evidence_tier") or "T3"),
                "synthetic": False,
                "location": {
                    "municipality_code": code,
                    "municipality_name": name,
                    "municipality": str(row.get("municipality") or ""),
                    "county_fips": code,
                    "state": "PR",
                    "country": "US",
                    "attribution_source": _ATTRIBUTION_SOURCE,
                    "attribution_confidence": conf,
                },
                "lineage": {
                    "producer_script": PRODUCER_SCRIPT,
                    "source_inputs": [str(row.get("source_url") or "")],
                    "extraction_method": "centinelas_pre_official_signal",
                },
            }
        )
    return candidates


def ingest_centinelas_drops(
    intake_dir: Path | str | None = None,
    *,
    root: Path | str = REPO_ROOT,
) -> dict[str, Any]:
    """Read Centinelas drops and return located pre-official finance candidates.

    ``awards`` holds the candidate funding-award rows; ``flows`` is reserved for a
    future transaction lane (empty today — Centinelas signals are pre-award).
    """
    intake_dir = Path(intake_dir) if intake_dir is not None else default_intake_dir(root)
    drops = load_drops(intake_dir)
    if not drops:
        return {"awards": [], "flows": [], "count": 0, "status": "NO_FILES"}

    finance = [payload for _, payload in drops if is_finance_relevant(payload)]
    awards = build_candidates(finance, root=root)
    status = "OK" if awards else "EMPTY"
    log.info(
        "Centinelas intake: %d drop(s), %d finance-relevant, %d candidate(s)",
        len(drops),
        len(finance),
        len(awards),
    )
    return {"awards": awards, "flows": [], "count": len(awards), "status": status}


__all__ = [
    "FINANCE_LABELS",
    "SOURCE_ID",
    "build_candidates",
    "default_intake_dir",
    "ingest_centinelas_drops",
    "is_finance_relevant",
    "load_drops",
]
