"""Build campaign-finance entity products without name-only identity promotion.

Normalized names are discovery keys only.  They may surface candidate entities,
but they never populate a resolved identity or promote a canonical relationship.
Stable FEC IDs are authoritative within this source plane.  Records without an
authoritative identifier remain explicitly CANDIDATE_NOT_IDENTITY.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from scripts import build_campaign_finance_entities as legacy
from scripts.campaign_finance_common import stable_id
from scripts.config import PROJECT_ROOT, setup_logging

CANDIDATE_STATUS = "CANDIDATE_NOT_IDENTITY"
VERIFIED_STATUS = "VERIFIED_ID"

RECIPIENT_COLUMNS = legacy.RECIPIENT_COLUMNS + [
    "candidate_count",
    "candidate_entity_ids",
    "candidate_entity_names",
    "candidate_entity_types",
    "candidate_identity_bases",
    "identity_status",
]
EDGE_COLUMNS = legacy.EDGE_COLUMNS + [
    "identity_status",
    "source_identity_basis",
    "target_identity_basis",
]


def _as_text(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def _mark_entity_identity(frame: pd.DataFrame, *, id_column: str) -> pd.DataFrame:
    result = frame.copy()
    ids = result.get(id_column, pd.Series("", index=result.index)).fillna("").astype(str).str.strip()
    verified = ids != ""
    result["identity_status"] = verified.map({True: VERIFIED_STATUS, False: CANDIDATE_STATUS})
    if "review_status" in result.columns:
        result.loc[~verified, "review_status"] = "needs_review"
    if "confidence" in result.columns:
        result.loc[~verified, "confidence"] = 0
    return result


def _candidate_index(
    processed: Path,
    candidates: pd.DataFrame,
    committees: pd.DataFrame,
) -> dict[str, list[dict[str, str]]]:
    """Return full normalized-name candidate sets; never collapse ties."""
    index: dict[str, list[dict[str, str]]] = {}

    def add(normalized: str, *, entity_id: str, name: str, entity_type: str, basis: str) -> None:
        if not normalized:
            return
        record = {
            "entity_id": entity_id,
            "name": name,
            "entity_type": entity_type,
            "identity_basis": basis,
        }
        bucket = index.setdefault(normalized, [])
        if record not in bucket:
            bucket.append(record)

    for row in candidates.itertuples():
        add(
            _as_text(getattr(row, "normalized_name", "")),
            entity_id=_as_text(getattr(row, "candidate_entity_id", "")),
            name=_as_text(getattr(row, "canonical_name", "")),
            entity_type="candidate",
            basis="fec_candidate_id"
            if _as_text(getattr(row, "fec_candidate_id", ""))
            else "normalized_name_discovery_only",
        )
    for row in committees.itertuples():
        add(
            _as_text(getattr(row, "normalized_name", "")),
            entity_id=_as_text(getattr(row, "committee_entity_id", "")),
            name=_as_text(getattr(row, "canonical_name", "")),
            entity_type="committee",
            basis="fec_committee_id"
            if _as_text(getattr(row, "fec_committee_id", ""))
            else "normalized_name_discovery_only",
        )

    for filename, name_col, id_col, entity_type, id_basis in (
        ("ngos/ngos_master.csv", "legal_name", "ngo_id", "ngo", "ngo_id"),
        ("entities_resolved.csv", "canonical_name", "entity_id", "entity", "entity_id"),
        ("pr_all_awards_master.csv", "recipient_name", "recipient_uei", "award_recipient", "recipient_uei"),
    ):
        for _, row in legacy._read(processed / filename).iterrows():
            name = _as_text(row.get(name_col, ""))
            normalized = legacy._normalize(name)
            identifier = _as_text(row.get(id_col, ""))
            add(
                normalized,
                entity_id=identifier,
                name=name,
                entity_type=entity_type,
                basis=id_basis if identifier else "normalized_name_discovery_only",
            )

    return {key: sorted(value, key=lambda item: (item["entity_type"], item["entity_id"], item["name"])) for key, value in index.items()}


def resolve_recipients(
    processed: Path,
    candidates: pd.DataFrame,
    committees: pd.DataFrame,
) -> pd.DataFrame:
    frame = legacy._read(processed / "pr_fec_disbursements.csv")
    if frame.empty or "recipient_name" not in frame:
        return pd.DataFrame(columns=RECIPIENT_COLUMNS)

    index = _candidate_index(processed, candidates, committees)
    frame["normalized_name"] = frame["recipient_name"].map(legacy._normalize)
    frame["numeric_amount"] = pd.to_numeric(
        frame.get("disbursement_amount", ""), errors="coerce"
    ).fillna(0)
    output: list[dict[str, Any]] = []
    for normalized, group in frame[frame["normalized_name"] != ""].groupby("normalized_name"):
        candidate_set = index.get(normalized, [])
        output.append(
            {
                "recipient_resolution_id": stable_id("recipient", normalized),
                "recipient_name": legacy._first(group["recipient_name"]),
                "normalized_name": normalized,
                "resolved_entity_id": "",
                "resolved_entity_name": "",
                "resolved_entity_type": "unresolved",
                "match_method": "normalized_name_discovery_only" if candidate_set else "unresolved",
                "confidence": 0,
                "review_status": "needs_review",
                "total_disbursements": float(group["numeric_amount"].sum()),
                "disbursement_count": len(group),
                "committees_paying": legacy._pipe(group.get("committee_name", [])),
                "cycles": legacy._pipe(group.get("cycle", [])),
                "source_dataset": "fec_schedule_b",
                "candidate_count": len(candidate_set),
                "candidate_entity_ids": json.dumps(
                    [item["entity_id"] for item in candidate_set], ensure_ascii=False
                ),
                "candidate_entity_names": json.dumps(
                    [item["name"] for item in candidate_set], ensure_ascii=False
                ),
                "candidate_entity_types": json.dumps(
                    [item["entity_type"] for item in candidate_set], ensure_ascii=False
                ),
                "candidate_identity_bases": json.dumps(
                    [item["identity_basis"] for item in candidate_set], ensure_ascii=False
                ),
                "identity_status": CANDIDATE_STATUS if candidate_set else "UNRESOLVED",
            }
        )
    return pd.DataFrame(output, columns=RECIPIENT_COLUMNS).sort_values(
        "total_disbursements", ascending=False
    )


def build_edges(
    processed: Path,
    candidates: pd.DataFrame,
    committees: pd.DataFrame,
) -> pd.DataFrame:
    candidate_ids = {
        _as_text(row.fec_candidate_id): _as_text(row.candidate_entity_id)
        for row in candidates.itertuples()
        if _as_text(row.fec_candidate_id)
    }
    committee_ids = {
        _as_text(row.fec_committee_id): _as_text(row.committee_entity_id)
        for row in committees.itertuples()
        if _as_text(row.fec_committee_id)
    }
    edges: list[dict[str, Any]] = []

    for i, row in legacy._read(processed / "pr_fec_contributions.csv").iterrows():
        target = committee_ids.get(_as_text(row.get("committee_id", "")))
        donor_raw = _as_text(row.get("contributor_name", ""))
        donor = legacy._normalize(donor_raw)
        if not target or not donor:
            continue
        source_record_id = stable_id(
            "fec_schedule_a_actor_record",
            _as_text(row.get("transaction_id", "")) or i,
            donor,
            _as_text(row.get("contribution_receipt_date", "")),
            _as_text(row.get("contribution_receipt_amount", "")),
        )
        edges.append(
            {
                "edge_id": stable_id("cfedge", "fec_a", i, source_record_id, target),
                "source_entity_id": source_record_id,
                "source_entity_type": "unresolved_donor_record",
                "edge_type": "CONTRIBUTED_TO",
                "target_entity_id": target,
                "target_entity_type": "committee",
                "amount": row.get("contribution_receipt_amount", ""),
                "transaction_date": row.get("contribution_receipt_date", ""),
                "cycle": row.get("cycle", ""),
                "support_oppose_indicator": "",
                "source_dataset": "fec_schedule_a",
                "confidence": 0,
                "identity_status": CANDIDATE_STATUS,
                "source_identity_basis": "transaction_record_only",
                "target_identity_basis": "fec_committee_id",
            }
        )

    for i, row in legacy._read(processed / "pr_fec_independent_expenditures.csv").iterrows():
        source_fec_id = _as_text(row.get("committee_id", ""))
        target_fec_id = _as_text(row.get("candidate_id", ""))
        source = committee_ids.get(source_fec_id)
        target = candidate_ids.get(target_fec_id)
        if not source:
            continue
        verified = bool(target)
        if not target:
            candidate_name = _as_text(row.get("candidate_name", ""))
            normalized = legacy._normalize(candidate_name)
            target = stable_id(
                "fec_schedule_e_candidate_record",
                _as_text(row.get("transaction_id", "")) or i,
                normalized,
            )
        indicator = _as_text(row.get("support_oppose_indicator", ""))
        edge_type = (
            "SUPPORTED"
            if indicator.upper().startswith("S")
            else "OPPOSED"
            if indicator.upper().startswith("O")
            else "INDEPENDENT_EXPENDITURE_FOR"
        )
        edges.append(
            {
                "edge_id": stable_id("cfedge", "fec_e", i, source, target),
                "source_entity_id": source,
                "source_entity_type": "committee",
                "edge_type": edge_type,
                "target_entity_id": target,
                "target_entity_type": "candidate" if verified else "unresolved_candidate_record",
                "amount": row.get("expenditure_amount", ""),
                "transaction_date": row.get("expenditure_date", ""),
                "cycle": row.get("cycle", ""),
                "support_oppose_indicator": indicator,
                "source_dataset": "fec_schedule_e",
                "confidence": 98 if verified else 0,
                "identity_status": VERIFIED_STATUS if verified else CANDIDATE_STATUS,
                "source_identity_basis": "fec_committee_id",
                "target_identity_basis": "fec_candidate_id" if verified else "normalized_name_discovery_only",
            }
        )
    return pd.DataFrame(edges, columns=EDGE_COLUMNS)


def run(root: Path | None = None) -> dict[str, object]:
    root = Path(root) if root else PROJECT_ROOT
    processed = root / "data" / "staging" / "processed"
    processed.mkdir(parents=True, exist_ok=True)

    candidates = _mark_entity_identity(legacy.build_candidates(processed), id_column="fec_candidate_id")
    committees = _mark_entity_identity(legacy.build_committees(processed), id_column="fec_committee_id")
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
        "identity_policy": "NO_NAME_ONLY_PROMOTION",
        "candidates": len(candidates),
        "candidate_unresolved_identity": int((candidates["identity_status"] != VERIFIED_STATUS).sum()) if len(candidates) else 0,
        "committees": len(committees),
        "committee_unresolved_identity": int((committees["identity_status"] != VERIFIED_STATUS).sum()) if len(committees) else 0,
        "recipients": len(recipients),
        "resolved_recipients": int((recipients["resolved_entity_id"].fillna("") != "").sum()) if len(recipients) else 0,
        "recipient_candidate_sets": int((pd.to_numeric(recipients["candidate_count"], errors="coerce").fillna(0) > 0).sum()) if len(recipients) else 0,
        "edges": len(edges),
        "verified_identity_edges": int((edges["identity_status"] == VERIFIED_STATUS).sum()) if len(edges) else 0,
        "candidate_identity_edges": int((edges["identity_status"] == CANDIDATE_STATUS).sum()) if len(edges) else 0,
    }
    setup_logging("build_campaign_finance_entities_certified").info(json.dumps(result))
    return result


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
