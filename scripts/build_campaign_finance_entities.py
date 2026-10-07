"""Build campaign-finance entities, recipient resolution, and graph edges."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from scripts.analyze_political_crossref import _normalize
except ImportError:  # pragma: no cover - isolated operator/test fallback
    import re

    def _normalize(name: str) -> str:
        text = re.sub(r"[^\w\s]", " ", str(name or "").upper())
        return re.sub(r"\s+", " ", text).strip()


from scripts.campaign_finance_common import stable_id
from scripts.config import PROJECT_ROOT, setup_logging

CANDIDATE_COLUMNS = [
    "candidate_entity_id",
    "fec_candidate_id",
    "canonical_name",
    "normalized_name",
    "aliases",
    "party",
    "office_sought",
    "jurisdiction",
    "cycles",
    "source_datasets",
    "source_record_count",
    "confidence",
    "review_status",
]
COMMITTEE_COLUMNS = [
    "committee_entity_id",
    "fec_committee_id",
    "canonical_name",
    "normalized_name",
    "aliases",
    "committee_type",
    "designation",
    "party",
    "state",
    "cycles",
    "source_datasets",
    "source_record_count",
    "confidence",
    "review_status",
]
RECIPIENT_COLUMNS = [
    "recipient_resolution_id",
    "recipient_name",
    "normalized_name",
    "identity_state",
    "candidate_set",
    "resolved_entity_id",
    "resolved_entity_name",
    "resolved_entity_type",
    "match_method",
    "confidence",
    "review_status",
    "total_disbursements",
    "disbursement_count",
    "committees_paying",
    "cycles",
    "source_dataset",
]
EDGE_COLUMNS = [
    "edge_id",
    "source_entity_id",
    "source_entity_type",
    "edge_type",
    "target_entity_id",
    "target_entity_type",
    "amount",
    "transaction_date",
    "cycle",
    "support_oppose_indicator",
    "source_dataset",
    "confidence",
]


def _read(path: Path) -> pd.DataFrame:
    return (
        pd.read_csv(path, dtype=str, low_memory=False).fillna("")
        if path.exists()
        else pd.DataFrame()
    )


def _pipe(values) -> str:
    return "|".join(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))


def _first(values) -> str:
    return next((str(v).strip() for v in values if str(v).strip()), "")


def _status(confidence: int) -> str:
    return "confirmed" if confidence >= 90 else "probable" if confidence >= 70 else "needs_review"


def _committee_like(row: pd.Series) -> bool:
    text = " ".join(
        str(row.get(c, ""))
        for c in ("candidate_or_committee", "candidacy_type", "office_sought", "report_type")
    ).lower()
    return any(x in text for x in ("comite", "comité", "committee", "partido", "pac"))


def _group_entities(records, *, kind: str) -> pd.DataFrame:
    """Build canonical FEC entities only from authoritative FEC identifiers.

    ID-less source rows remain in their RAW/NORMALIZED source datasets. They are
    discovery observations, not canonical entity identities, and therefore may
    not be collapsed by normalized name.
    """
    columns = CANDIDATE_COLUMNS if kind == "candidate" else COMMITTEE_COLUMNS
    if not records:
        return pd.DataFrame(columns=columns)
    frame = pd.DataFrame(records)
    frame["normalized_name"] = frame["name"].map(_normalize)
    frame = frame[frame["normalized_name"] != ""]
    output = []
    id_field = f"fec_{kind}_id"
    entity_field = f"{kind}_entity_id"
    frame[id_field] = frame[id_field].map(lambda value: str(value).strip())
    frame = frame[frame[id_field] != ""]
    if frame.empty:
        return pd.DataFrame(columns=columns)

    for fec_id, group in frame.groupby(id_field, sort=True):
        normalized = _first(group["normalized_name"])
        sources = sorted(set(group["source"]))
        confidence = 100
        canonical = _first(group["name"])
        aliases = sorted(
            {str(v).strip() for v in group["name"] if str(v).strip() not in {"", canonical}}
        )
        common = {
            entity_field: fec_id,
            id_field: fec_id,
            "canonical_name": canonical,
            "normalized_name": normalized,
            "aliases": json.dumps(aliases, ensure_ascii=False),
            "party": _pipe(group["party"]),
            "cycles": _pipe(sorted(set(group["cycle"]))),
            "source_datasets": "|".join(sources),
            "source_record_count": len(group),
            "confidence": confidence,
            "review_status": "confirmed",
        }
        if kind == "candidate":
            common.update(
                office_sought=_pipe(group["office"]),
                jurisdiction=_pipe(group["jurisdiction"]),
            )
        else:
            common.update(
                committee_type=_pipe(group["entity_type"]),
                designation=_pipe(group["designation"]),
                state=_pipe(group["state"]),
            )
        output.append(common)
    return pd.DataFrame(output, columns=columns).sort_values("canonical_name")


def build_candidates(processed: Path) -> pd.DataFrame:
    records = []
    for filename, source in (
        ("pr_fec_contributions.csv", "fec_schedule_a"),
        ("pr_fec_independent_expenditures.csv", "fec_schedule_e"),
    ):
        for _, row in _read(processed / filename).iterrows():
            fec_id = str(row.get("candidate_id", "")).strip()
            name = str(row.get("candidate_name", "")).strip() or fec_id
            if not name:
                continue
            records.append(
                dict(
                    fec_candidate_id=fec_id,
                    name=name,
                    party=row.get("party", ""),
                    office=_pipe(
                        [
                            row.get("office", ""),
                            row.get("office_state", ""),
                            row.get("office_district", ""),
                        ]
                    ),
                    jurisdiction=row.get("office_state", "") or "US",
                    cycle=row.get("cycle", ""),
                    source=source,
                )
            )
    for filename, source in (("pr_donaciones.csv", "cee"), ("pr_oce_donations.csv", "oce")):
        for _, row in _read(processed / filename).iterrows():
            name = str(row.get("candidate_or_committee", "")).strip()
            if name and not _committee_like(row):
                records.append(
                    dict(
                        fec_candidate_id="",
                        name=name,
                        party=row.get("party", ""),
                        office=row.get("office_sought", "") or row.get("candidacy_type", ""),
                        jurisdiction="PR",
                        cycle=row.get("cycle", ""),
                        source=source,
                    )
                )
    return _group_entities(records, kind="candidate")


def build_committees(processed: Path) -> pd.DataFrame:
    records = []
    for _, row in _read(processed / "pr_fec_committees.csv").iterrows():
        fec_id = str(row.get("committee_id", "")).strip()
        name = str(row.get("name", "")).strip() or fec_id
        if name:
            records.append(
                dict(
                    fec_committee_id=fec_id,
                    name=name,
                    entity_type=row.get("committee_type_full", "") or row.get("committee_type", ""),
                    designation=row.get("designation_full", "") or row.get("designation", ""),
                    party=row.get("party_full", "") or row.get("party", ""),
                    state=row.get("state", ""),
                    cycle=row.get("cycle", ""),
                    source="fec_master",
                )
            )
    for _, row in _read(processed / "pr_fec_contributions.csv").iterrows():
        fec_id = str(row.get("committee_id", "")).strip()
        name = str(row.get("committee_name", "")).strip() or fec_id
        if name:
            records.append(
                dict(
                    fec_committee_id=fec_id,
                    name=name,
                    entity_type="",
                    designation="",
                    party="",
                    state="",
                    cycle=row.get("cycle", ""),
                    source="fec_schedule_a",
                )
            )
    for _, row in _read(processed / "pr_oce_reports.csv").iterrows():
        name = str(row.get("committee_name", "")).strip()
        if name:
            records.append(
                dict(
                    fec_committee_id="",
                    name=name,
                    entity_type=row.get("report_type", ""),
                    designation="",
                    party="",
                    state="PR",
                    cycle="",
                    source="oce_reports",
                )
            )
    for filename, source in (("pr_donaciones.csv", "cee"), ("pr_oce_donations.csv", "oce")):
        for _, row in _read(processed / filename).iterrows():
            name = str(row.get("candidate_or_committee", "")).strip()
            if name and _committee_like(row):
                records.append(
                    dict(
                        fec_committee_id="",
                        name=name,
                        entity_type=row.get("candidacy_type", ""),
                        designation="",
                        party=row.get("party", ""),
                        state="PR",
                        cycle=row.get("cycle", ""),
                        source=source,
                    )
                )
    return _group_entities(records, kind="committee")


def _resolution_index(processed: Path, candidates, committees):
    """Return authoritative ID bindings plus name-only discovery candidates."""
    id_index: dict[str, tuple[str, str, str]] = {}
    name_candidates: dict[str, list[dict[str, str]]] = {}

    def add_candidate(
        *,
        stable_id_value: str,
        name: str,
        entity_type: str,
        authoritative_id: str,
        source: str,
    ) -> None:
        stable_id_value = str(stable_id_value).strip()
        authoritative_id = str(authoritative_id).strip()
        normalized = _normalize(name)
        if not stable_id_value or not authoritative_id:
            return
        id_index[authoritative_id] = (stable_id_value, name, entity_type)
        if normalized:
            name_candidates.setdefault(normalized, []).append(
                {
                    "entity_id": stable_id_value,
                    "entity_name": name,
                    "entity_type": entity_type,
                    "authoritative_id": authoritative_id,
                    "source": source,
                }
            )

    for row in candidates.itertuples():
        add_candidate(
            stable_id_value=row.candidate_entity_id,
            name=row.canonical_name,
            entity_type="candidate",
            authoritative_id=row.fec_candidate_id,
            source="fec_candidate",
        )
    for row in committees.itertuples():
        add_candidate(
            stable_id_value=row.committee_entity_id,
            name=row.canonical_name,
            entity_type="committee",
            authoritative_id=row.fec_committee_id,
            source="fec_committee",
        )

    sources = (
        ("ngos/ngos_master.csv", "legal_name", "ngo_id", "ngo"),
        ("entities_resolved.csv", "canonical_name", "entity_id", "entity"),
        ("pr_all_awards_master.csv", "recipient_name", "recipient_uei", "award_recipient"),
    )
    for filename, name_col, id_col, entity_type in sources:
        for _, row in _read(processed / filename).iterrows():
            authoritative_id = str(row.get(id_col, "")).strip()
            name = str(row.get(name_col, "")).strip()
            normalized = _normalize(name)
            if not authoritative_id or not normalized:
                continue
            name_candidates.setdefault(normalized, []).append(
                {
                    "entity_id": authoritative_id,
                    "entity_name": name,
                    "entity_type": entity_type,
                    "authoritative_id": authoritative_id,
                    "source": filename,
                }
            )

    for normalized, candidates_for_name in name_candidates.items():
        deduped = {
            (
                item["entity_id"],
                item["entity_type"],
                item["authoritative_id"],
                item["source"],
            ): item
            for item in candidates_for_name
        }
        name_candidates[normalized] = [
            deduped[key] for key in sorted(deduped)
        ]
    return id_index, name_candidates


def resolve_recipients(processed: Path, candidates, committees) -> pd.DataFrame:
    frame = _read(processed / "pr_fec_disbursements.csv")
    if frame.empty or "recipient_name" not in frame:
        return pd.DataFrame(columns=RECIPIENT_COLUMNS)
    id_index, name_candidates = _resolution_index(processed, candidates, committees)
    frame["normalized_name"] = frame["recipient_name"].map(_normalize)
    frame["numeric_amount"] = pd.to_numeric(
        frame.get("disbursement_amount", ""), errors="coerce"
    ).fillna(0)
    output = []
    for normalized, group in frame[frame["normalized_name"] != ""].groupby("normalized_name"):
        direct_ids: set[str] = set()
        for column in ("recipient_committee_id", "recipient_id", "candidate_id"):
            if column in group:
                direct_ids.update(
                    str(value).strip()
                    for value in group[column]
                    if str(value).strip()
                )
        direct_matches = {
            id_index[identifier]
            for identifier in direct_ids
            if identifier in id_index
        }
        candidates_for_name = name_candidates.get(normalized, [])
        candidate_payload = json.dumps(candidates_for_name, ensure_ascii=False, sort_keys=True)

        if len(direct_matches) == 1:
            entity_id, entity_name, entity_type = next(iter(direct_matches))
            confidence = 100
            match_method = "authoritative_recipient_id"
            identity_state = "AUTHORITATIVE_ID"
            review_status = "confirmed"
        else:
            entity_id = ""
            entity_name = ""
            entity_type = "unresolved"
            confidence = 0
            review_status = "needs_review"
            if len(direct_matches) > 1:
                match_method = "authoritative_id_tie"
                identity_state = "REVIEW_UNRESOLVED_TIE"
            elif candidates_for_name:
                match_method = "name_candidate_only"
                identity_state = "CANDIDATE_NOT_IDENTITY"
            else:
                match_method = "unresolved"
                identity_state = "UNRESOLVED"

        output.append(
            dict(
                recipient_resolution_id=stable_id("recipient", normalized),
                recipient_name=_first(group["recipient_name"]),
                normalized_name=normalized,
                identity_state=identity_state,
                candidate_set=candidate_payload,
                resolved_entity_id=entity_id,
                resolved_entity_name=entity_name,
                resolved_entity_type=entity_type,
                match_method=match_method,
                confidence=confidence,
                review_status=review_status,
                total_disbursements=float(group["numeric_amount"].sum()),
                disbursement_count=len(group),
                committees_paying=_pipe(group.get("committee_name", [])),
                cycles=_pipe(group.get("cycle", [])),
                source_dataset="fec_schedule_b",
            )
        )
    return pd.DataFrame(output, columns=RECIPIENT_COLUMNS).sort_values(
        "total_disbursements", ascending=False
    )


def build_edges(processed: Path, candidates, committees) -> pd.DataFrame:
    """Emit only graph edges whose endpoints have authoritative FEC IDs."""
    candidate_ids = {
        str(r.fec_candidate_id): str(r.candidate_entity_id)
        for r in candidates.itertuples()
        if str(r.fec_candidate_id).strip()
    }
    committee_ids = {
        str(r.fec_committee_id): str(r.committee_entity_id)
        for r in committees.itertuples()
        if str(r.fec_committee_id).strip()
    }
    edges = []

    for i, row in _read(processed / "pr_fec_disbursements.csv").iterrows():
        source = committee_ids.get(str(row.get("committee_id", "")).strip())
        recipient_id = str(
            row.get("recipient_committee_id", "") or row.get("recipient_id", "")
        ).strip()
        target = committee_ids.get(recipient_id)
        if not source or not target:
            continue
        record_id = str(row.get("sub_id", "") or row.get("transaction_id", "") or i)
        edges.append(
            dict(
                edge_id=stable_id("cfedge", "fec_b", record_id, source, target),
                source_entity_id=source,
                source_entity_type="committee",
                edge_type="TRANSFERRED_TO",
                target_entity_id=target,
                target_entity_type="committee",
                amount=row.get("disbursement_amount", ""),
                transaction_date=row.get("disbursement_date", ""),
                cycle=row.get("cycle", ""),
                support_oppose_indicator="",
                source_dataset="fec_schedule_b",
                confidence=100,
            )
        )

    for i, row in _read(processed / "pr_fec_independent_expenditures.csv").iterrows():
        source = committee_ids.get(str(row.get("committee_id", "")).strip())
        target = candidate_ids.get(str(row.get("candidate_id", "")).strip())
        if not source or not target:
            continue
        indicator = str(row.get("support_oppose_indicator", ""))
        record_id = str(row.get("sub_id", "") or row.get("transaction_id", "") or i)
        edge_type = (
            "SUPPORTED"
            if indicator.upper().startswith("S")
            else "OPPOSED"
            if indicator.upper().startswith("O")
            else "INDEPENDENT_EXPENDITURE_FOR"
        )
        edges.append(
            dict(
                edge_id=stable_id("cfedge", "fec_e", record_id, source, target),
                source_entity_id=source,
                source_entity_type="committee",
                edge_type=edge_type,
                target_entity_id=target,
                target_entity_type="candidate",
                amount=row.get("expenditure_amount", ""),
                transaction_date=row.get("expenditure_date", ""),
                cycle=row.get("cycle", ""),
                support_oppose_indicator=indicator,
                source_dataset="fec_schedule_e",
                confidence=100,
            )
        )
    return pd.DataFrame(edges, columns=EDGE_COLUMNS)


def run(root: Path | None = None) -> dict[str, object]:
    root = Path(root) if root else PROJECT_ROOT
    processed = root / "data" / "staging" / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    candidates = build_candidates(processed)
    committees = build_committees(processed)
    recipients = resolve_recipients(processed, candidates, committees)
    edges = build_edges(processed, candidates, committees)
    outputs = {
        "candidates": candidates,
        "committees": committees,
        "recipient_resolution": recipients,
        "edges": edges,
    }
    for key, frame in outputs.items():
        frame.to_csv(processed / f"pr_campaign_finance_{key}.csv", index=False)
    result = {
        "status": "OK",
        "candidates": len(candidates),
        "committees": len(committees),
        "recipients": len(recipients),
        "resolved_recipients": int((recipients["resolved_entity_type"] != "unresolved").sum())
        if len(recipients)
        else 0,
        "edges": len(edges),
    }
    setup_logging("build_campaign_finance_entities").info(json.dumps(result))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
