"""Canonical political-finance graph construction.

The module is deliberately dataframe-first so it can be used by both batch
materialization scripts and the API/GUI layer without requiring a graph
database. Every emitted node and edge carries provenance and confidence.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping

import pandas as pd


ENTITY_COLUMNS = [
    "entity_id",
    "entity_type",
    "canonical_name",
    "jurisdiction",
    "source_id",
    "source_record_id",
    "confidence",
    "provenance",
]
EDGE_COLUMNS = [
    "edge_id",
    "source_entity_id",
    "target_entity_id",
    "edge_type",
    "amount",
    "transaction_date",
    "cycle",
    "support_oppose",
    "source_id",
    "source_record_id",
    "confidence",
    "provenance",
]
RESOLUTION_COLUMNS = [
    "source_id",
    "source_record_id",
    "raw_recipient_name",
    "resolved_entity_id",
    "resolved_name",
    "resolution_method",
    "identity_state",
    "candidate_entity_ids",
    "confidence",
    "review_required",
]
CORRELATION_COLUMNS = [
    "political_entity_id",
    "external_entity_id",
    "external_dataset",
    "relationship_type",
    "match_method",
    "confidence",
    "evidence",
]


_COMMITTEE_TYPES = {
    "N": "PAC",
    "Q": "PAC",
    "O": "SUPER_PAC",
    "U": "SUPER_PAC",
    "X": "PARTY_COMMITTEE",
    "Y": "PARTY_COMMITTEE",
    "Z": "NATIONAL_PARTY_NONFEDERAL",
    "H": "CAMPAIGN_COMMITTEE",
    "S": "CAMPAIGN_COMMITTEE",
    "P": "CAMPAIGN_COMMITTEE",
}


def normalize_name(value: object) -> str:
    """Return a conservative normalized organization/person name."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = unicodedata.normalize("NFKD", str(value)).encode("ascii", "ignore").decode()
    text = text.upper().replace("&", " AND ")
    text = re.sub(r"[^A-Z0-9]+", " ", text)
    tokens = [t for t in text.split() if t not in {"THE"}]
    return " ".join(tokens)


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(normalize_name(p) for p in parts)
    return f"{prefix}_{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def classify_committee(row: Mapping[str, object]) -> str:
    """Classify FEC/PR committees into graph entity types.

    Explicit text labels win over compact FEC codes. Joint fundraising and
    527 organizations are retained as distinct classes.
    """
    text = " ".join(
        normalize_name(row.get(k, ""))
        for k in ("committee_type_full", "designation_full", "organization_type", "name")
    )
    if "JOINT FUNDRAISING" in text:
        return "JOINT_FUNDRAISING_COMMITTEE"
    if "527" in text:
        return "POLITICAL_527"
    if "INDEPENDENT EXPENDITURE ONLY" in text or "SUPER PAC" in text:
        return "SUPER_PAC"
    code = normalize_name(row.get("committee_type", ""))
    return _COMMITTEE_TYPES.get(code, "POLITICAL_COMMITTEE")


@dataclass(frozen=True)
class Resolution:
    entity_id: str
    name: str
    method: str
    confidence: float


def _entity_index(frames: Iterable[tuple[str, pd.DataFrame]]) -> dict[str, list[Resolution]]:
    index: dict[str, list[Resolution]] = {}
    for source, frame in frames:
        if frame is None or frame.empty:
            continue
        id_col = next(
            (
                c
                for c in ("entity_id", "recipient_id", "awardee_id", "ein", "committee_id")
                if c in frame
            ),
            None,
        )
        name_col = next(
            (
                c
                for c in (
                    "canonical_name",
                    "name",
                    "recipient_name",
                    "awardee_name",
                    "organization_name",
                    "committee_name",
                )
                if c in frame
            ),
            None,
        )
        if not id_col or not name_col:
            continue
        for row in frame[[id_col, name_col]].dropna().drop_duplicates().itertuples(index=False):
            raw_id, raw_name = str(row[0]), str(row[1])
            key = normalize_name(raw_name)
            if not key:
                continue
            index.setdefault(key, []).append(
                Resolution(
                    entity_id=f"{source}:{raw_id}",
                    name=raw_name,
                    method=f"exact_normalized_name:{source}",
                    confidence=0.98,
                )
            )
    return index


def recipient_candidates(
    name: object,
    index: Mapping[str, list[Resolution]],
) -> list[Resolution]:
    """Return the full name-discovery candidate set without promoting identity."""
    candidates = index.get(normalize_name(name), [])
    unique = {candidate.entity_id: candidate for candidate in candidates}
    return [unique[key] for key in sorted(unique)]


def resolve_recipient(name: object, index: Mapping[str, list[Resolution]]) -> Resolution | None:
    """Name-only resolution is intentionally disabled.

    This compatibility function remains importable for callers that previously
    expected it, but determinism or a unique normalized-name candidate is not
    identity evidence. Callers should use :func:`recipient_candidates` for
    discovery and require an independent authoritative binding to resolve.
    """
    del name, index
    return None


def _fec_entity_id(raw_id: object) -> tuple[str, str] | None:
    value = str(raw_id or "").strip().upper()
    if not value:
        return None
    if value.startswith("C"):
        return f"fec_committee:{value}", "POLITICAL_COMMITTEE"
    if value.startswith(("H", "S", "P")):
        return f"fec_candidate:{value}", "CANDIDATE"
    return None


def _stable_source_identity(row: Mapping[str, object], source: str) -> str | None:
    for key in ("contributor_id", "donor_id", "entity_id", "uei", "ein"):
        value = row.get(key)
        if value not in (None, "") and not pd.isna(value):
            return f"{source}:{key}:{str(value).strip()}"
    return None


def _record_id(row: Mapping[str, object], fallback: str) -> str:
    for key in ("sub_id", "transaction_id", "file_number", "image_number", "record_id"):
        value = row.get(key)
        if value not in (None, "") and not pd.isna(value):
            return str(value)
    return fallback


def build_political_finance_graph(
    *,
    contributions: pd.DataFrame | None = None,
    committees: pd.DataFrame | None = None,
    disbursements: pd.DataFrame | None = None,
    independent_expenditures: pd.DataFrame | None = None,
    oce_donations: pd.DataFrame | None = None,
    cee_donations: pd.DataFrame | None = None,
    entity_frames: Iterable[tuple[str, pd.DataFrame]] = (),
) -> dict[str, pd.DataFrame]:
    """Build canonical entities, edges, resolutions and external correlations."""
    entities: dict[str, dict] = {}
    edges: dict[str, dict] = {}
    resolutions: list[dict] = []
    index = _entity_index(entity_frames)

    def add_entity(
        entity_id: str,
        entity_type: str,
        name: object,
        source: str,
        record_id: str,
        confidence: float = 1.0,
        jurisdiction: str = "",
    ) -> None:
        entities.setdefault(
            entity_id,
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "canonical_name": str(name or "").strip(),
                "jurisdiction": jurisdiction,
                "source_id": source,
                "source_record_id": record_id,
                "confidence": confidence,
                "provenance": f"{source}:{record_id}",
            },
        )

    def add_edge(
        source_entity: str,
        target_entity: str,
        edge_type: str,
        row: Mapping[str, object],
        source: str,
        record_id: str,
        amount_key: str = "",
        date_key: str = "",
        confidence: float = 1.0,
        support_oppose: str = "",
    ) -> None:
        edge_id = _stable_id("pfe", source, record_id, source_entity, target_entity, edge_type)
        edges[edge_id] = {
            "edge_id": edge_id,
            "source_entity_id": source_entity,
            "target_entity_id": target_entity,
            "edge_type": edge_type,
            "amount": row.get(amount_key, "") if amount_key else "",
            "transaction_date": row.get(date_key, "") if date_key else "",
            "cycle": row.get("cycle", ""),
            "support_oppose": support_oppose,
            "source_id": source,
            "source_record_id": record_id,
            "confidence": confidence,
            "provenance": f"{source}:{record_id}",
        }

    if committees is not None:
        for row in committees.fillna("").to_dict("records"):
            cid = str(row.get("committee_id") or "").strip().upper()
            if not cid:
                continue
            add_entity(
                f"fec_committee:{cid}",
                classify_committee(row),
                row.get("name"),
                "fec_committees",
                cid,
                jurisdiction=str(row.get("state", "")),
            )

    receipt_frames = (
        ("fec_schedule_a", contributions),
        ("oce", oce_donations),
        ("cee", cee_donations),
    )
    for source, frame in receipt_frames:
        if frame is None or frame.empty:
            continue
        for i, row in enumerate(frame.fillna("").to_dict("records")):
            rid = _record_id(row, str(i))
            donor_name = row.get("contributor_name") or row.get("donor_name") or row.get("name")
            donor_id = _stable_source_identity(row, source)
            committee_id = str(
                row.get("committee_id") or row.get("recipient_committee_id") or ""
            ).strip().upper()
            target = _fec_entity_id(committee_id)
            if donor_id is None or target is None or target[1] != "POLITICAL_COMMITTEE":
                continue
            target_id, _ = target
            committee_name = row.get("committee_name") or row.get("recipient_name") or committee_id
            add_entity(donor_id, "DONOR", donor_name, source, rid, 1.0)
            add_entity(target_id, "POLITICAL_COMMITTEE", committee_name, source, rid, 1.0)
            add_edge(
                donor_id,
                target_id,
                "DONATED_TO",
                row,
                source,
                rid,
                amount_key=next(
                    (
                        k
                        for k in ("contribution_receipt_amount", "amount", "donation_amount")
                        if k in row
                    ),
                    "",
                ),
                date_key=next(
                    (k for k in ("contribution_receipt_date", "date", "donation_date") if k in row),
                    "",
                ),
                confidence=1.0,
            )

    if disbursements is not None:
        for i, row in enumerate(disbursements.fillna("").to_dict("records")):
            rid = _record_id(row, str(i))
            source_binding = _fec_entity_id(row.get("committee_id", ""))
            recipient_raw_id = (
                row.get("recipient_committee_id")
                or row.get("recipient_id")
                or row.get("candidate_id")
                or ""
            )
            target_binding = _fec_entity_id(recipient_raw_id)
            name_candidates = recipient_candidates(row.get("recipient_name"), index)
            candidate_entity_ids = [candidate.entity_id for candidate in name_candidates]

            if source_binding is not None and source_binding[1] == "POLITICAL_COMMITTEE":
                source_id, _ = source_binding
                add_entity(
                    source_id,
                    "POLITICAL_COMMITTEE",
                    row.get("committee_name"),
                    "fec_schedule_b",
                    rid,
                    1.0,
                )
            else:
                source_id = ""

            if target_binding is not None:
                target_id, target_type = target_binding
                target_name = row.get("recipient_name") or recipient_raw_id
                method = "authoritative_fec_id"
                identity_state = "AUTHORITATIVE_ID"
                confidence = 1.0
                add_entity(
                    target_id,
                    target_type,
                    target_name,
                    "fec_schedule_b",
                    rid,
                    confidence,
                )
                if source_id:
                    add_edge(
                        source_id,
                        target_id,
                        "DISBURSED_TO",
                        row,
                        "fec_schedule_b",
                        rid,
                        "disbursement_amount",
                        "disbursement_date",
                        confidence,
                    )
                resolved_id = target_id
                resolved_name = str(target_name or "")
                review_required = False
            else:
                method = "name_candidate_only" if name_candidates else "unresolved"
                identity_state = (
                    "CANDIDATE_NOT_IDENTITY" if name_candidates else "UNRESOLVED"
                )
                confidence = 0.0
                resolved_id = ""
                resolved_name = ""
                review_required = True

            resolutions.append(
                {
                    "source_id": "fec_schedule_b",
                    "source_record_id": rid,
                    "raw_recipient_name": row.get("recipient_name", ""),
                    "resolved_entity_id": resolved_id,
                    "resolved_name": resolved_name,
                    "resolution_method": method,
                    "identity_state": identity_state,
                    "candidate_entity_ids": json.dumps(
                        candidate_entity_ids,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "confidence": confidence,
                    "review_required": review_required,
                }
            )

    if independent_expenditures is not None:
        for i, row in enumerate(independent_expenditures.fillna("").to_dict("records")):
            rid = _record_id(row, str(i))
            committee_binding = _fec_entity_id(row.get("committee_id", ""))
            candidate_binding = _fec_entity_id(row.get("candidate_id", ""))
            if (
                committee_binding is None
                or committee_binding[1] != "POLITICAL_COMMITTEE"
                or candidate_binding is None
                or candidate_binding[1] != "CANDIDATE"
            ):
                continue
            committee_id, _ = committee_binding
            candidate_id, _ = candidate_binding
            add_entity(
                committee_id,
                "POLITICAL_COMMITTEE",
                row.get("committee_name"),
                "fec_schedule_e",
                rid,
                1.0,
            )
            add_entity(
                candidate_id,
                "CANDIDATE",
                row.get("candidate_name"),
                "fec_schedule_e",
                rid,
                1.0,
            )
            indicator = normalize_name(row.get("support_oppose_indicator"))
            edge_type = (
                "INDEPENDENT_EXPENDITURE_AGAINST"
                if indicator.startswith("O")
                else "INDEPENDENT_EXPENDITURE_FOR"
            )
            add_edge(
                committee_id,
                candidate_id,
                edge_type,
                row,
                "fec_schedule_e",
                rid,
                "expenditure_amount",
                "expenditure_date",
                1.0,
                indicator,
            )

    entity_df = (
        pd.DataFrame(entities.values(), columns=ENTITY_COLUMNS).sort_values("entity_id")
        if entities
        else pd.DataFrame(columns=ENTITY_COLUMNS)
    )
    edge_df = (
        pd.DataFrame(edges.values(), columns=EDGE_COLUMNS).sort_values("edge_id")
        if edges
        else pd.DataFrame(columns=EDGE_COLUMNS)
    )
    resolution_df = pd.DataFrame(resolutions, columns=RESOLUTION_COLUMNS)

    correlations = []
    for item in resolutions:
        if item["resolved_entity_id"]:
            correlations.append(
                {
                    "political_entity_id": _stable_id(
                        "unresolved_recipient", item["raw_recipient_name"]
                    ),
                    "external_entity_id": item["resolved_entity_id"],
                    "external_dataset": item["resolution_method"].split(":")[-1],
                    "relationship_type": "RESOLVED_AS",
                    "match_method": item["resolution_method"],
                    "confidence": item["confidence"],
                    "evidence": f"normalized_name={normalize_name(item['raw_recipient_name'])}",
                }
            )
    correlation_df = pd.DataFrame(correlations, columns=CORRELATION_COLUMNS)
    return {
        "entities": entity_df,
        "edges": edge_df,
        "resolutions": resolution_df,
        "correlations": correlation_df,
    }


def find_flow_paths(edges: pd.DataFrame, origin_entity_id: str, max_hops: int = 4) -> pd.DataFrame:
    """Enumerate simple downstream paths from an origin entity."""
    if edges.empty or max_hops < 1:
        return pd.DataFrame(columns=["origin_entity_id", "terminal_entity_id", "hop_count", "path"])
    adjacency: dict[str, list[str]] = {}
    for row in (
        edges[["source_entity_id", "target_entity_id"]].drop_duplicates().itertuples(index=False)
    ):
        adjacency.setdefault(str(row[0]), []).append(str(row[1]))
    results = []
    stack = [(origin_entity_id, [origin_entity_id])]
    while stack:
        node, path = stack.pop()
        if len(path) - 1 >= max_hops:
            continue
        for nxt in adjacency.get(node, []):
            if nxt in path:
                continue
            new_path = path + [nxt]
            results.append(
                {
                    "origin_entity_id": origin_entity_id,
                    "terminal_entity_id": nxt,
                    "hop_count": len(new_path) - 1,
                    "path": " > ".join(new_path),
                }
            )
            stack.append((nxt, new_path))
    return pd.DataFrame(results).drop_duplicates()
