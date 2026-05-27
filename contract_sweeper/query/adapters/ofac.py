"""OFAC SDN entity-mode adapter.

Wraps ``https://www.treasury.gov/ofac/downloads/sdn.xml`` matching
``scripts/download_ofac.py``. Treasury publishes the full Specially
Designated Nationals list as a single XML file; we fetch it once,
parse it client-side, and filter against the caller's identifiers.

No credentials required. The full list is small enough (~10K entries)
to fit easily in memory.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any, Iterable

import pandas as pd

from contract_sweeper.runtime.retry_runtime import RetryPolicy, with_retry

from ..entity_types import EntityQuery
from .entity_base import EntityAdapter

OFAC_SDN_XML = "https://www.treasury.gov/ofac/downloads/sdn.xml"


def _strip_ns(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _text(node: ET.Element, local_name: str) -> str:
    for child in node:
        if _strip_ns(child.tag) == local_name:
            return (child.text or "").strip()
    return ""


def _collect(node: ET.Element, local_name: str) -> Iterable[ET.Element]:
    for child in node.iter():
        if _strip_ns(child.tag) == local_name:
            yield child


def _aka_names(entry: ET.Element) -> list[str]:
    names: list[str] = []
    for aka in _collect(entry, "aka"):
        last = _text(aka, "lastName")
        first = _text(aka, "firstName")
        full = f"{last}, {first}".strip(", ") if first else last
        if full:
            names.append(full)
    return names


def parse_sdn_xml(content: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(content)
    entries = [e for e in root.iter() if _strip_ns(e.tag) == "sdnEntry"]
    rows: list[dict[str, Any]] = []
    for entry in entries:
        last = _text(entry, "lastName")
        first = _text(entry, "firstName")
        name = f"{last}, {first}".strip(", ") if first else last
        programs = sorted({
            (p.text or "").strip() for p in _collect(entry, "program") if (p.text or "").strip()
        })
        rows.append({
            "uid": _text(entry, "uid"),
            "name": name,
            "sdn_type": _text(entry, "sdnType"),
            "programs": "|".join(programs),
            "aka_names": "|".join(_aka_names(entry)),
        })
    return rows


class OFACSDNAdapter(EntityAdapter):
    source_id = "ofac_sdn"
    supported_kinds = frozenset({"uei", "name"})

    def __init__(self, *, root, session=None):
        super().__init__(root=root)
        self._session = session

    def _get_session(self):
        if self._session is not None:
            return self._session
        import requests

        s = requests.Session()
        s.headers.update({
            "Accept": "application/xml,text/xml",
            "User-Agent": "contract-sweeper-query/1",
        })
        return s

    def _download(self, session) -> bytes:
        resp = session.get(OFAC_SDN_XML, timeout=120)
        resp.raise_for_status()
        return resp.content

    def fetch(self, query: EntityQuery) -> pd.DataFrame:
        session = self._get_session()
        policy = RetryPolicy(max_attempts=4, base_delay_seconds=1.0, max_delay_seconds=15.0)

        xml_bytes = with_retry(lambda: self._download(session), policy=policy)
        all_rows = parse_sdn_xml(xml_bytes)
        if not all_rows:
            return pd.DataFrame()

        target_names = {n.lower() for n in query.by_kind("name")}
        target_ueis = {u.upper() for u in query.by_kind("uei")}
        if not target_names and not target_ueis:
            return pd.DataFrame()

        def _matches(row: dict[str, Any]) -> bool:
            name_lower = (row.get("name") or "").lower()
            aka_lower = (row.get("aka_names") or "").lower()
            uid_upper = (row.get("uid") or "").upper()
            if target_names:
                if any(t in name_lower or t in aka_lower for t in target_names):
                    return True
            if target_ueis and uid_upper in target_ueis:
                return True
            return False

        filtered = [r for r in all_rows if _matches(r)]
        return pd.DataFrame(filtered) if filtered else pd.DataFrame()
