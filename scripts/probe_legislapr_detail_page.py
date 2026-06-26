#!/usr/bin/env python3
"""Compatibility wrapper for the canonical LegislaPR detail probe.

The implementation lives in scripts/probe_legislapr_detail.py so the source
registry, tests, and operator docs share one ingestion path. This module keeps
the first-pass API available for older tests and operator commands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable
from urllib.parse import quote

from scripts.probe_legislapr_detail import (
    LEGISLAPR_BASE,
    _fiscal_language_detected,
    _promotion_status,
    fetch_html,
    main,
    measure_id_from_url,
    parse_legislapr_detail,
)


@dataclass(frozen=True)
class LegislativeDiscoveryRecord:
    source_id: str
    measure_id: str
    detail_url: str
    openstates_url: str | None
    official_document_url: str | None
    outbound_urls: list[str]
    fiscal_signal: bool
    fiscal_terms: list[str]
    promotion_state: str


FISCAL_KEYWORDS = {
    "asignacion",
    "asignación",
    "asignar",
    "fondos",
    "fondo",
    "presupuesto",
    "reembolso",
    "subvencion",
    "subvención",
    "incentivo",
    "contrato",
    "contratacion",
    "contratación",
    "municipio",
    "cor3",
    "fema",
    "cdbg",
}


def normalize_measure_id(value: str) -> str:
    compact = measure_id_from_url(f"{LEGISLAPR_BASE}/bills/{value}")
    match = re.match(r"([A-Z]+)(\d+)$", compact)
    if not match:
        raise ValueError(f"Unsupported Puerto Rico measure id: {value!r}")
    return f"{match.group(1)} {int(match.group(2))}"


def legislapr_detail_url(measure_id: str) -> str:
    return f"{LEGISLAPR_BASE}/bills/{quote(normalize_measure_id(measure_id))}"


def promotion_state(openstates_url: str | None, official_document_url: str | None) -> str:
    status = _promotion_status(openstates_url or "", official_document_url or "")
    if status == "cross_confirmed_candidate":
        return "cross_confirmed_ready"
    if openstates_url or official_document_url:
        return "partially_confirmed_hold"
    return "discovery_only_hold"


def fiscal_terms(text: str) -> list[str]:
    lowered = text.lower()
    return sorted(term for term in FISCAL_KEYWORDS if term in lowered)


def probe_measure(measure_id: str, html: str | None = None) -> LegislativeDiscoveryRecord:
    detail_url = legislapr_detail_url(measure_id)
    page = html if html is not None else fetch_html(detail_url)
    parsed = parse_legislapr_detail(page, detail_url)
    state = promotion_state(parsed.openstates_url or None, parsed.sutra_url or None)
    return LegislativeDiscoveryRecord(
        source_id=parsed.source_system,
        measure_id=normalize_measure_id(measure_id),
        detail_url=detail_url,
        openstates_url=parsed.openstates_url or None,
        official_document_url=parsed.sutra_url or None,
        outbound_urls=parsed.document_urls,
        fiscal_signal=_fiscal_language_detected(page),
        fiscal_terms=fiscal_terms(page),
        promotion_state=state,
    )


def iter_measure_ids(values: Iterable[str]) -> Iterable[str]:
    for value in values:
        yield normalize_measure_id(value)


if __name__ == "__main__":
    raise SystemExit(main())
